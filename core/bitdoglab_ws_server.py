"""
Servidor WebSocket local para receber dados da BitDogLab (RP2040).

Roda num thread separado, com seu proprio loop asyncio, pra nao
bloquear a interface PySide6. Guarda a ultima leitura recebida (de
qualquer teste) e expoe um callback opcional (`on_message`) pra quem
quiser reagir em tempo real a QUALQUER mensagem (ex.: atualizar a tela
ou alimentar o Random Forest).

Protocolo do teste de forca via joystick (teste_avc_joystick - ver
websocket_client.c / teste_avc.c no repositorio da BitDogLab) ja
definido e tratado aqui:

    {"tipo": "inicio_teste"}
    {"tipo": "resultado_direcao", "direcao": "<DIRECAO>", "sucesso": <bool>}
    {"tipo": "resumo", "direita": <bool>, "esquerda": <bool>,
     "cima": <bool>, "baixo": <bool>, "geral": <bool>}

O estado desse teste fica acumulado em self.joystick (dict) e pode ser
lido a qualquer momento com get_joystick_status(), alem de continuar
disponivel cru em get_latest() / on_message() como qualquer outra
mensagem.

TODO: o protocolo dos sensores MAX30102/ADS8232 e do teste de sorriso
ainda nao foi definido nesta conversa. Quando estiver, adicione o
tratamento do novo "tipo" em `_dispatch`, do mesmo jeito que foi feito
para "inicio_teste"/"resultado_direcao"/"resumo" do joystick abaixo -
um bloco de estado (self.<teste> = {...}) + um metodo
get_<teste>_status() com o mesmo formato.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading

import websockets

log = logging.getLogger("bitdoglab_ws")

# Mesmos textos que o firmware antigo (versao so-serial, sem Wi-Fi)
# imprimia em "Resultado geral: ...", mantidos so pra quem consome
# resultado_geral como texto continuar funcionando sem precisar mudar
# pra bool.
_TEXTO_RESULTADO_GERAL = {
    True: "SEM INDICIOS DE FRAQUEZA",
    False: "POSSIVEL FRAQUEZA DETECTADA",
}

# "direita" (JSON, minusculo) <-> "DIREITA" (chave usada em joystick["direcoes"]).
_CHAVE_JSON_PARA_DIRECAO = {
    "direita": "DIREITA",
    "esquerda": "ESQUERDA",
    "cima": "CIMA",
    "baixo": "BAIXO",
}


def _joystick_status_vazio() -> dict:
    return {
        "direcoes": {},          # ex.: {"DIREITA": True, "ESQUERDA": False, ...}
        "resultado_geral": None,
        "direcao_atual": None,       # nao vem no protocolo atual (firmware so manda o resultado final)
        "segundos_restantes": None,  # idem
    }


class BitDogLabServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765, on_message=None):
        self.host = host
        self.port = port
        self.on_message = on_message  # callback(dict) opcional, chamado a cada mensagem

        self._latest: dict | None = None
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop_event: asyncio.Event | None = None

        # Estado acumulado do teste do joystick (ver docstring do modulo).
        self.joystick: dict = _joystick_status_vazio()

    def start(self):
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None:
            self._thread.join(timeout=2)

    def get_latest(self) -> dict | None:
        with self._lock:
            return self._latest

    def get_joystick_status(self) -> dict:
        with self._lock:
            return {
                "direcoes": dict(self.joystick["direcoes"]),
                "resultado_geral": self.joystick["resultado_geral"],
                "direcao_atual": self.joystick["direcao_atual"],
                "segundos_restantes": self.joystick["segundos_restantes"],
            }

    # -- internos --
    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            log.exception("Servidor WebSocket da BitDogLab encerrou com erro")

    async def _serve(self):
        try:
            async with websockets.serve(self._handler, self.host, self.port):
                log.info("Servidor WebSocket da BitDogLab em ws://%s:%s", self.host, self.port)
                await self._stop_event.wait()
        except OSError:
            log.exception(
                "Nao foi possivel abrir a porta %s (ja em uso?). "
                "O resto da aplicacao continua funcionando sem dados da BitDogLab.",
                self.port,
            )

    async def _handler(self, websocket):
        log.info("BitDogLab conectada: %s", websocket.remote_address)
        try:
            async for raw in websocket:
                self._handle_message(raw)
        except websockets.exceptions.ConnectionClosed:
            log.info("BitDogLab desconectada")

    def _handle_message(self, raw: str):
        try:
            data = json.loads(raw)
            print(data)
        except json.JSONDecodeError:
            log.warning("Mensagem nao-JSON recebida da BitDogLab: %r", raw)
            return

        with self._lock:
            self._latest = data
            self._dispatch(data)

        if self.on_message:
            self.on_message(data)

    def _dispatch(self, data: dict):
        """Atualiza o estado especifico de cada teste, por 'tipo'.

        Chamado com self._lock ja adquirido. Mensagens com 'tipo'
        desconhecido (testes cujo protocolo ainda nao foi definido) sao
        ignoradas aqui - continuam disponiveis cruas via get_latest()/
        on_message().
        """
        tipo = data.get("tipo")

        if tipo == "inicio_teste":
            self.joystick = _joystick_status_vazio()
            return

        if tipo == "resultado_direcao":
            direcao = data.get("direcao")
            sucesso = data.get("sucesso")
            if isinstance(direcao, str) and isinstance(sucesso, bool):
                self.joystick["direcoes"][direcao] = sucesso
                self.joystick["direcao_atual"] = None
            else:
                log.warning("resultado_direcao com campos invalidos: %r", data)
            return

        if tipo == "resumo":
            for chave_json, direcao in _CHAVE_JSON_PARA_DIRECAO.items():
                if chave_json in data and isinstance(data[chave_json], bool):
                    self.joystick["direcoes"][direcao] = data[chave_json]
            geral = data.get("geral")
            if isinstance(geral, bool):
                self.joystick["resultado_geral"] = _TEXTO_RESULTADO_GERAL[geral]
            self.joystick["direcao_atual"] = None
            return

        # tipo desconhecido (sorriso, sensores, etc.) - sem tratamento ainda,
        # veja o TODO no topo do arquivo.