"""
Leitor serial do teste de forca via joystick - teste_avc_joystick.

Esse firmware roda num Pico comum (sem Wi-Fi, ver [[bitdoglab-firmware]])
e so imprime o resultado via USB serial (printf) - nao ha protocolo
estruturado (JSON etc.), so texto solto pensado pra um humano ler no
monitor serial. O teste em si roda inteiramente na placa: o usuario
aperta o Botao A nela pra iniciar, o codigo aqui so ESCUTA a porta
serial e atualiza a tela.

Este leitor roda numa thread separada e faz um parsing simples das
linhas que interessam (ver teste_avc.c no repositorio):

    "== Teste: <DIRECAO> =="                          (comeca o teste de uma direcao)
    "Segurando <DIRECAO>: faltam <N> s"                (contagem regressiva segurando)
    "Sucesso: segurou <DIRECAO> por <N> ms"
    "Falha: forca caiu antes de completar o tempo em <DIRECAO>"
    "Falha: tempo esgotado tentando alcancar <DIRECAO>"
    "Resultado geral: <SEM INDICIOS DE FRAQUEZA | POSSIVEL FRAQUEZA DETECTADA>"
    "Aguardando botao A para iniciar o teste..."       (idle - reseta a seta)

TODO: se o texto do printf no firmware mudar, ajuste as regexes
abaixo. O ideal a longo prazo seria o firmware imprimir uma linha
estruturada (ex. "RESULT:{...}" em JSON) pra facilitar o parsing -
mudanca de firmware, fora do escopo desta conversa.
"""

from __future__ import annotations

import logging
import re
import threading

try:
    import serial
except ImportError:  # pragma: no cover - ambiente de dev sem pyserial ainda
    serial = None

log = logging.getLogger("bitdoglab_serial")

_RE_TESTE_INICIA = re.compile(r"== Teste: (\w+) ==")
_RE_SEGURANDO = re.compile(r"Segurando (\w+): faltam (\d+) s")
_RE_SUCESSO = re.compile(r"Sucesso: segurou (\w+) por (\d+) ms")
_RE_FALHA_CAIU = re.compile(r"Falha: forca caiu antes de completar o tempo em (\w+)")
_RE_FALHA_TEMPO = re.compile(r"Falha: tempo esgotado tentando alcancar (\w+)")
_RE_RESULTADO_GERAL = re.compile(r"Resultado geral: (.+)")
_RE_IDLE = re.compile(r"Aguardando botao A")


class JoystickTestSerialReader:
    def __init__(self, port: str, baudrate: int = 115200, on_line=None, on_result=None):
        self.port = port
        self.baudrate = baudrate
        self.on_line = on_line       # callback(str) - cada linha bruta recebida
        self.on_result = on_result   # callback(dict) - chamado a cada atualizacao de resultado

        self._ser = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self.direcoes: dict[str, bool] = {}   # ex.: {"DIREITA": True, "ESQUERDA": False, ...}
        self.resultado_geral: str | None = None
        self.direcao_atual: str | None = None      # direcao sendo testada agora (p/ animar a seta)
        self.segundos_restantes: int | None = None  # contagem regressiva enquanto segura

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

    def _run(self):
        try:
            self._ser = serial.Serial(self.port, self.baudrate, timeout=1)
        except Exception:
            log.exception("Nao foi possivel abrir a porta serial %s", self.port)
            return

        log.info("Lendo BitDogLab (teste do joystick) em %s", self.port)
        while not self._stop.is_set():
            try:
                raw = self._ser.readline()
            except Exception:
                break
            if not raw:
                continue
            linha = raw.decode(errors="replace").strip()
            if not linha:
                continue

            if self.on_line:
                self.on_line(linha)
            self._parse_linha(linha)

    def _parse_linha(self, linha: str):
        m = _RE_TESTE_INICIA.search(linha)
        if m:
            self.direcao_atual = m.group(1)
            self.segundos_restantes = None
            self._emit_result()
            return

        m = _RE_SEGURANDO.search(linha)
        if m:
            self.direcao_atual = m.group(1)
            self.segundos_restantes = int(m.group(2))
            self._emit_result()
            return

        m = _RE_SUCESSO.search(linha)
        if m:
            self.direcoes[m.group(1)] = True
            self.direcao_atual = None
            self.segundos_restantes = None
            self._emit_result()
            return

        m = _RE_FALHA_CAIU.search(linha) or _RE_FALHA_TEMPO.search(linha)
        if m:
            self.direcoes[m.group(1)] = False
            self.direcao_atual = None
            self.segundos_restantes = None
            self._emit_result()
            return

        m = _RE_RESULTADO_GERAL.search(linha)
        if m:
            self.resultado_geral = m.group(1).strip()
            self.direcao_atual = None
            self._emit_result()
            return

        if _RE_IDLE.search(linha):
            self.direcao_atual = None
            self.segundos_restantes = None
            self._emit_result()

    def _emit_result(self):
        if self.on_result:
            self.on_result({
                "direcoes": dict(self.direcoes),
                "resultado_geral": self.resultado_geral,
                "direcao_atual": self.direcao_atual,
                "segundos_restantes": self.segundos_restantes,
            })

    def reset(self):
        self.direcoes.clear()
        self.resultado_geral = None
        self.direcao_atual = None
        self.segundos_restantes = None