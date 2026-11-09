"""Read NeuroTriagem's joystick trajectory protocol (version 2) over USB.

The board owns calibration, acquisition and progression through the three shapes.
Results describe movement in normalized joystick units, not clinical weakness.
JOYSTICK_POSICAO records provide optional live position and target telemetry.
Optional JOYSTICK_AMOSTRA records arrive after results, never as live telemetry.
Callbacks run on the reader thread; GUI callers must forward them via Qt signals.
"""

from __future__ import annotations

from copy import deepcopy
import logging
import math
import threading

try:
    import serial
except ImportError:
    serial = None

log = logging.getLogger("bitdoglab_serial")
FORMAS = ("QUADRADO", "TRIANGULO", "CIRCULO")
_ESTADOS_RESULTADO = ("CONCLUIDO", "TEMPO_LIMITE", "NAO_INICIADO")
_MAX_LINE_BYTES = 8192


def _fields(line):
    parts = line.split(",")
    fields = {}
    for part in parts[1:]:
        key, separator, value = part.strip().partition("=")
        if not separator or not key or not value or key in fields:
            raise ValueError("Campo serial inválido")
        fields[key] = value.strip()
    return parts[0], fields


def _integer(fields, key, minimum=0, maximum=0xFFFFFFFF):
    value = fields[key]
    if not value.isascii() or not value.isdecimal():
        raise ValueError(f"Inteiro inválido: {key}")
    value = int(value)
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"Inteiro fora do intervalo: {key}")
    return value


def _number(fields, key, minimum=0.0, maximum=None):
    value = float(fields[key])
    if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"Número inválido: {key}")
    return value


def _choice(fields, key, choices):
    value = fields[key]
    if value not in choices:
        raise ValueError(f"Valor desconhecido: {key}")
    return value


class JoystickTestSerialReader:
    def __init__(self, port: str, baudrate: int = 115200, on_line=None,
                 on_result=None, on_connection=None, on_sample=None,
                 on_position=None):
        self.port = port
        self.baudrate = baudrate
        self.on_line = on_line
        self.on_result = on_result
        self.on_connection = on_connection
        self.on_sample = on_sample
        self.on_position = on_position
        self._ser = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pending = bytearray()
        self._discard_line = False
        self.reset()

    def reset(self):
        self.estado = "AGUARDANDO"
        self.protocolo = None
        self.configuracao = {}
        self.calibracao = {}
        self.forma_atual = None
        self.resultados = {}
        self.final = None
        self.mensagem = None
        self._unsupported_protocol = False
        self._position_timestamps = {}
        self._positions_closed = False

    @staticmethod
    def _notify(callback, value):
        if callback is not None:
            try:
                callback(value)
            except Exception:
                log.exception("Erro no callback do leitor do joystick")

    def _emit_connection(self, estado, mensagem):
        self._notify(self.on_connection, {"estado": estado, "mensagem": mensagem})

    def _emit_result(self):
        self._notify(self.on_result, deepcopy({
            "estado": self.estado,
            "protocolo": self.protocolo,
            "configuracao": self.configuracao,
            "calibracao": self.calibracao,
            "forma_atual": self.forma_atual,
            "resultados": self.resultados,
            "final": self.final,
            "mensagem": self.mensagem,
        }))

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        if serial is None:
            self._emit_connection("ERRO", "pyserial não está instalado. Instale as dependências do projeto.")
            return
        self._stop.clear()
        self._pending.clear()
        self._discard_line = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                log.debug("Porta serial já encerrada", exc_info=True)
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _run(self):
        failed = False
        try:
            self._ser = serial.Serial(self.port, self.baudrate, timeout=0.2)
            if not self._stop.is_set():
                self._emit_connection("CONECTADO", f"Conectado à porta {self.port}.")
            while not self._stop.is_set():
                raw = self._ser.readline()
                if raw:
                    self._consume_chunk(raw)
        except Exception as exc:
            if not self._stop.is_set():
                failed = True
                log.warning("Falha na porta serial %s: %s", self.port, exc)
                self._emit_connection("ERRO", f"Não foi possível ler a porta {self.port}: {exc}")
        finally:
            connection, self._ser = self._ser, None
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    log.debug("Erro ao encerrar a porta serial", exc_info=True)
            if not failed:
                self._emit_connection("DESCONECTADO", "Porta serial desconectada.")

    def _consume_chunk(self, raw: bytes):
        """Keep partial timeout reads until newline, and bound noisy input."""
        for chunk in raw.splitlines(keepends=True):
            complete = chunk.endswith(b"\n")
            if not self._discard_line:
                self._pending.extend(chunk)
                if len(self._pending) > _MAX_LINE_BYTES:
                    self._pending.clear()
                    self._discard_line = True
            if complete:
                if not self._discard_line:
                    line = self._pending.decode("utf-8", errors="replace").strip()
                    if line:
                        self._notify(self.on_line, line)
                        self._parse_linha(line)
                self._pending.clear()
                self._discard_line = False

    def _parse_linha(self, linha: str):
        """Apply only valid records; unrelated OXI lines are ignored."""
        linha = linha.strip()
        if linha.startswith("Aguardando botao A"):
            if self.estado not in ("FINALIZADO", "CANCELADO", "ERRO"):
                self.estado = "AGUARDANDO"
                self.forma_atual = None
                self.mensagem = "Aguardando o botão A na BitDogLab."
                self._emit_result()
            return
        if not linha.startswith("JOYSTICK_"):
            return
        try:
            event, fields = _fields(linha)
            self._apply_event(event, fields)
        except (KeyError, ValueError, OverflowError):
            log.debug("Registro do joystick ignorado: %s", linha)

    def _apply_event(self, event, fields):
        if event == "JOYSTICK_INICIO":
            protocol = _integer(fields, "protocolo", 1)
            if protocol != 2:
                self.reset()
                self.protocolo = protocol
                self._unsupported_protocol = True
                self.estado = "ERRO"
                self.mensagem = f"Protocolo do joystick {protocol} não suportado. Esta tela requer o protocolo 2."
                self._emit_result()
                return
            config = {
                "modelo": _choice(fields, "modelo", ("TRAJETORIAS_2D",)),
                "periodo_ms": _integer(fields, "periodo_ms", 1),
                "limite_ms": _integer(fields, "limite_ms", 1),
                "tolerancia_u": _number(fields, "tolerancia_u"),
                "forca_controlada": _integer(fields, "forca_controlada", 0, 0),
                "clinico": _integer(fields, "clinico", 0, 0),
            }
            if config["tolerancia_u"] <= 0:
                raise ValueError("Tolerância deve ser positiva")
            if "telemetria_ms" in fields:
                config["telemetria_ms"] = _integer(fields, "telemetria_ms", 1)
            self.reset()
            self.protocolo = protocol
            self.configuracao = config
            self.estado = "CALIBRANDO"
            self.mensagem = "Solte o joystick e mantenha-o parado durante a calibração."
        elif self._unsupported_protocol:
            return
        elif event == "JOYSTICK_CALIBRACAO":
            calibration = {key: _integer(fields, key, 0, 4095) for key in ("centro_x", "centro_y")}
            self.calibracao = calibration
            self.estado = "PRONTO"
            self.mensagem = "Centro calibrado. Aguarde a primeira figura."
        elif event == "JOYSTICK_ETAPA":
            shape = _choice(fields, "forma", FORMAS)
            phase = _choice(fields, "fase", ("POSICIONAR", "PERCURSO"))
            self.forma_atual = shape
            self.estado = phase
            self.mensagem = None
        elif event == "JOYSTICK_POSICAO":
            self._apply_position(fields)
            return
        elif event == "JOYSTICK_RESULTADO":
            result = {
                "forma": _choice(fields, "forma", FORMAS),
                "estado": _choice(fields, "estado", _ESTADOS_RESULTADO),
                "progresso": _integer(fields, "progresso", 0, 100),
                "amostras": _integer(fields, "amostras"),
                "valido": _integer(fields, "valido", 0, 1),
                "tempo_ms": _integer(fields, "tempo_ms"),
                "npv": _integer(fields, "npv"),
                "maior_intervalo_ms": _integer(fields, "maior_intervalo_ms"),
                "area": _choice(fields, "area", ("NA",)),
                "clinico": _integer(fields, "clinico", 0, 0),
            }
            for key in ("caminho_u", "vel_media_u_s", "acel_media_u_s2", "desvio_medio_u", "rmse_u"):
                result[key] = _number(fields, key)
            result["sobreposicao_pct"] = _number(fields, "sobreposicao_pct", 0, 100)
            self.resultados[result["forma"]] = result
            self.forma_atual = result["forma"]
            self.estado = "RESULTADO"
            self.mensagem = None
        elif event == "JOYSTICK_AMOSTRA":
            sample = {
                "forma": _choice(fields, "forma", FORMAS),
                "t_ms": _integer(fields, "t_ms"),
                "x": _number(fields, "x", -1, 1),
                "y": _number(fields, "y", -1, 1),
            }
            self._notify(self.on_sample, sample)
            return
        elif event == "JOYSTICK_FINAL":
            final = {
                "protocolo": _integer(fields, "protocolo", 2, 2),
                "concluidas": _integer(fields, "concluidas", 0, len(FORMAS)),
                "total": _integer(fields, "total", len(FORMAS), len(FORMAS)),
                "clinico": _integer(fields, "clinico", 0, 0),
            }
            self.final = final
            self._positions_closed = True
            self.estado = "FINALIZADO"
            self.mensagem = "Teste de trajetórias finalizado."
        elif event == "JOYSTICK_CANCELADO":
            self._positions_closed = True
            if self.final is not None:
                self.estado = "FINALIZADO"
                self.mensagem = "Teste finalizado. O botão B selecionou o oxímetro."
            else:
                self.estado = "CANCELADO"
                self.mensagem = "Teste interrompido pelo botão B. A placa iniciou o oxímetro."
        elif event == "JOYSTICK_ERRO":
            reason = fields["motivo"]
            calibration = {
                key: _integer(fields, key, 0, 4095)
                for key in ("centro_x", "centro_y", "ruido_x", "ruido_y") if key in fields
            }
            self.calibracao.update(calibration)
            self._positions_closed = True
            self.estado = "ERRO"
            self.mensagem = (
                "Centro instável ou deslocado. Solte o joystick e pressione A para repetir."
                if reason == "CALIBRACAO" else f"Erro no teste do joystick: {reason}."
            )
        else:
            return
        # Connecting midway is supported; these records identify protocol 2 even
        # when the session's start configuration was not received.
        if self.protocolo is None:
            self.protocolo = 2
        self._emit_result()

    def _apply_position(self, fields):
        """Forward live coordinates without copying results or storing samples.

        Timestamps restart when a new phase begins. A stage received from the
        board is authoritative; only a newly attached reader can infer it from
        its first position frame if it missed the corresponding ETAPA record.
        """
        if self._positions_closed or self.final is not None:
            return
        position = {
            "forma": _choice(fields, "forma", FORMAS),
            "fase": _choice(fields, "fase", ("POSICIONAR", "PERCURSO")),
            "t_ms": _integer(fields, "t_ms"),
            "x": _number(fields, "x", -1, 1),
            "y": _number(fields, "y", -1, 1),
            "alvo_x": _number(fields, "alvo_x", -1, 1),
            "alvo_y": _number(fields, "alvo_y", -1, 1),
            "passo": _integer(fields, "passo", 0, 48),
            "progresso": _integer(fields, "progresso", 0, 100),
        }
        phase_key = (position["forma"], position["fase"])
        previous_time = self._position_timestamps.get(phase_key)
        if previous_time is not None and position["t_ms"] <= previous_time:
            return
        infer_stage = self.estado == "AGUARDANDO" and self.protocolo is None
        if not infer_stage and (self.forma_atual, self.estado) != phase_key:
            return
        if infer_stage:
            self.protocolo = 2
            self.forma_atual, self.estado = phase_key
            self.mensagem = None
            self._emit_result()
        self._position_timestamps[phase_key] = position["t_ms"]
        self._notify(self.on_position, position)
