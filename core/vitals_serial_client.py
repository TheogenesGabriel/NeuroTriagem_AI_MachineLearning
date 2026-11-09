"""
Leitor serial da pre-triagem (oxigenacao + batimentos cardiacos).

Mesmo esquema do teste do joystick (core/bitdoglab_serial_client.py): o
firmware roda isolado na BitDogLab e so imprime texto pela USB serial.
O usuario aperta o Botao B na placa pra iniciar a leitura e o codigo
aqui so ESCUTA a porta e atualiza a tela.

Protocolo REAL do firmware (oximetro), tratado em _parse_oxi():

    "OXI_DEDO"                                     (dedo detectado - comeca a leitura)
    "OXI,t=<s>,bruto_fc=..,bruto_spo2=..,fc=..,spo2=..,valido=<0|1>,inl_fc=..,inl_spo2=.."
                                                   (1 linha por segundo; so usa fc/spo2
                                                    quando valido=1 - os campos bruto_* e
                                                    inl_* sao ignorados)
    "OXI_FINAL,fc=<X>,spo2=<Y>"                    (resultado final - conclui a leitura)

Linhas fora desse protocolo caem no parser generico abaixo (formato
antigo/alternativo: "SpO2: X | BPM: Y", "Resultado ...", "Falha: ...").

Formato generico (legado):

    "Aguardando botao B para iniciar a pre-triagem..."   (idle)
    "== Pre-triagem: lendo =="                           (comecou a leitura)
    "Lendo sinais vitais: faltam <N> s"                   (contagem regressiva)
    "SpO2: <X> % | BPM: <Y>"                              (leitura parcial, opcional)
    "Resultado pre-triagem: SpO2=<X> BPM=<Y>"             (valores finais)
    "Falha: <motivo>"                                     (ex.: dedo nao detectado)

As regexes sao tolerantes a maiusculas/minusculas e a espacos. Se o texto
do printf no firmware mudar, ajuste-as abaixo.

Valores fora da faixa fisiologica plausivel (ex.: 0 quando o sensor ainda
nao detectou o dedo) sao ignorados.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading

try:
    import serial
except ImportError:  # pragma: no cover - ambiente de dev sem pyserial ainda
    serial = None

log = logging.getLogger("vitals_serial")

_FLAGS = re.IGNORECASE

_RE_IDLE = re.compile(r"Aguardando botao B", _FLAGS)
_RE_INICIA = re.compile(r"==\s*Pre-?triagem:\s*lendo\s*==", _FLAGS)
_RE_PROGRESSO = re.compile(r"faltam\s+(\d+)\s*s", _FLAGS)
_NUM = r"(\d+(?:[.,]\d+)?)"
_RE_SPO2 = re.compile(
    r"(?:SpO\s*2|SpO\u2082|SP02|oxigena\w*|satura\w*|O2)\s*(?:\(%\))?\s*[:=\-]?\s*" + _NUM, _FLAGS
)
_RE_BPM = re.compile(
    r"(?:BPM|HR|heart\s*rate|batimentos?|freq\w*(?:\s+card\w*)?|pulso)\s*(?:\(bpm\))?\s*[:=\-]?\s*" + _NUM,
    _FLAGS,
)
# Qualquer linha que indique o fim da medicao (alem do formato combinado).
_RE_RESULTADO = re.compile(r"Resultado|Final|Conclu[ií]d|Fim da leitura|Leitura (?:ok|finalizada)", _FLAGS)
_RE_FALHA = re.compile(r"Falha:\s*(.+)", _FLAGS)

# Faixas plausiveis - fora disso o valor e descartado (sensor sem dedo etc.).
SPO2_MIN, SPO2_MAX = 50.0, 100.0
BPM_MIN, BPM_MAX = 30.0, 220.0

# Segundos sem nenhuma linha nova para considerar a leitura concluida
# (quando o firmware nao imprime uma linha de "resultado final").
IDLE_CONCLUI_S = 3

# Estados enviados no dict de on_update.
ESTADO_AGUARDANDO = "aguardando"
ESTADO_LENDO = "lendo"
ESTADO_CONCLUIDO = "concluido"
ESTADO_FALHA = "falha"


def default_serial_port() -> str:
    env = os.environ.get("BITDOGLAB_SERIAL_PORT")
    if env:
        return env
    if sys.platform.startswith("win"):
        return "COM5"
    if sys.platform == "darwin":
        return "/dev/tty.usbmodem0000"
    return "/dev/ttyACM0"


def _to_float(texto: str) -> float:
    return float(texto.replace(",", "."))


class VitalsSerialReader:
    def __init__(self, port: str, baudrate: int = 115200, on_line=None, on_update=None):
        self.port = port
        self.baudrate = baudrate
        self.on_line = on_line       # callback(str)  - cada linha bruta recebida
        self.on_update = on_update   # callback(dict) - a cada mudanca de estado/valor

        self._ser = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self.estado: str = ESTADO_AGUARDANDO
        self.segundos_restantes: int | None = None
        self.segundos_decorridos: int | None = None  # campo t= do protocolo OXI
        self.spo2: float | None = None        # ultimo valor valido (parcial ou final)
        self.heart_rate: float | None = None  # idem
        self.mensagem: str | None = None      # motivo da falha, se houver

    # -- ciclo de vida --
    def start(self):
        if serial is None:
            log.warning("pyserial nao instalado - nao e possivel ler a porta serial.")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)

    def reset(self):
        self.estado = ESTADO_AGUARDANDO
        self.segundos_restantes = None
        self.segundos_decorridos = None
        self.spo2 = None
        self.heart_rate = None
        self.mensagem = None

    # -- leitura --
    def _run(self):
        try:
            self._ser = serial.Serial(self.port, self.baudrate, timeout=1)
        except Exception:
            log.exception("Nao foi possivel abrir a porta serial %s", self.port)
            self.estado = ESTADO_FALHA
            self.mensagem = f"Nao foi possivel abrir a porta {self.port}"
            self._emit()
            return

        log.info("Lendo BitDogLab (pre-triagem) em %s", self.port)
        ociosos = 0  # leituras seguidas (1 s cada) sem nenhuma linha nova
        while not self._stop.is_set():
            try:
                raw = self._ser.readline()
            except Exception:
                break
            if not raw:
                ociosos += 1
                # Firmware que so imprime valores e depois silencia: se ja ha
                # SpO2 e BPM validos e a placa parou de enviar, considera concluido.
                if (
                    ociosos >= IDLE_CONCLUI_S
                    and self.estado == ESTADO_LENDO
                    and self.spo2 is not None
                    and self.heart_rate is not None
                ):
                    self.estado = ESTADO_CONCLUIDO
                    self.segundos_restantes = None
                    self._emit()
                continue
            ociosos = 0
            linha = raw.decode(errors="replace").strip()
            if not linha:
                continue

            if self.on_line:
                self.on_line(linha)
            self._parse_linha(linha)

    def _atualiza_valores(self, linha: str) -> bool:
        """Extrai SpO2/BPM da linha, se vierem e forem plausiveis."""
        mudou = False
        m = _RE_SPO2.search(linha)
        if m:
            valor = _to_float(m.group(1))
            if SPO2_MIN <= valor <= SPO2_MAX:
                self.spo2 = valor
                mudou = True
        m = _RE_BPM.search(linha)
        if m:
            valor = _to_float(m.group(1))
            if BPM_MIN <= valor <= BPM_MAX:
                self.heart_rate = valor
                mudou = True
        return mudou

    @staticmethod
    def _campos_oxi(resto: str) -> dict[str, str]:
        campos = {}
        for par in resto.split(","):
            chave, sep, valor = par.partition("=")
            if sep:
                campos[chave.strip().lower()] = valor.strip()
        return campos

    @staticmethod
    def _num_valido(texto: str | None, minimo: float, maximo: float) -> float | None:
        if texto is None:
            return None
        try:
            valor = _to_float(texto)
        except ValueError:
            return None
        return valor if minimo <= valor <= maximo else None

    def _parse_oxi(self, linha: str):
        tag, _, resto = linha.partition(",")
        tag = tag.strip().upper()
        campos = self._campos_oxi(resto)

        if tag == "OXI_DEDO":
            self.reset()
            self.estado = ESTADO_LENDO
            self._emit()
            return

        if tag == "OXI":
            if self.estado == ESTADO_CONCLUIDO:
                return  # linhas tardias depois do resultado final
            self.estado = ESTADO_LENDO
            try:
                self.segundos_decorridos = int(campos["t"])
            except (KeyError, ValueError):
                pass
            # So confia em fc/spo2 quando o firmware marca valido=1.
            if campos.get("valido") == "1":
                fc = self._num_valido(campos.get("fc"), BPM_MIN, BPM_MAX)
                spo2 = self._num_valido(campos.get("spo2"), SPO2_MIN, SPO2_MAX)
                if fc is not None:
                    self.heart_rate = fc
                if spo2 is not None:
                    self.spo2 = spo2
            self._emit()
            return

        if tag == "OXI_FINAL":
            fc = self._num_valido(campos.get("fc"), BPM_MIN, BPM_MAX)
            spo2 = self._num_valido(campos.get("spo2"), SPO2_MIN, SPO2_MAX)
            self.segundos_restantes = None
            if fc is not None and spo2 is not None:
                self.heart_rate = fc
                self.spo2 = spo2
                self.estado = ESTADO_CONCLUIDO
                self.mensagem = None
            else:
                self.estado = ESTADO_FALHA
                self.mensagem = "Leitura final invalida - tente novamente"
            self._emit()
            return

        if any(pal in tag for pal in ("FALHA", "ERRO", "TIMEOUT", "SEM_DEDO")):
            self.estado = ESTADO_FALHA
            self.mensagem = linha
            self._emit()
            return
        # Outras linhas OXI_* desconhecidas: so aparecem no log, sem efeito.

    def _parse_linha(self, linha: str):
        if linha.upper().startswith("OXI"):
            self._parse_oxi(linha)
            return

        if _RE_IDLE.search(linha):
            self.reset()
            self._emit()
            return

        if _RE_INICIA.search(linha):
            self.reset()
            self.estado = ESTADO_LENDO
            self._emit()
            return

        m = _RE_FALHA.search(linha)
        if m:
            self.estado = ESTADO_FALHA
            self.mensagem = m.group(1).strip()
            self.segundos_restantes = None
            self._emit()
            return

        if _RE_RESULTADO.search(linha):
            self._atualiza_valores(linha)
            self.segundos_restantes = None
            # So conclui se os dois valores finais chegaram validos.
            if self.spo2 is not None and self.heart_rate is not None:
                self.estado = ESTADO_CONCLUIDO
            else:
                self.estado = ESTADO_FALHA
                self.mensagem = "Leitura final invalida - tente novamente"
            self._emit()
            return

        m = _RE_PROGRESSO.search(linha)
        if m:
            self.estado = ESTADO_LENDO
            self.segundos_restantes = int(m.group(1))
            self._atualiza_valores(linha)
            self._emit()
            return

        # Leitura parcial ("SpO2: 97 % | BPM: 72") durante a medicao.
        if self._atualiza_valores(linha):
            if self.estado != ESTADO_CONCLUIDO:
                self.estado = ESTADO_LENDO
            self._emit()

    def _emit(self):
        if self.on_update:
            self.on_update({
                "estado": self.estado,
                "segundos_restantes": self.segundos_restantes,
                "segundos_decorridos": self.segundos_decorridos,
                "spo2": self.spo2,
                "heart_rate": self.heart_rate,
                "mensagem": self.mensagem,
            })
