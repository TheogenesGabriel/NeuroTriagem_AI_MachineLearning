"""Replay the actual firmware protocol without requiring a connected board."""

import unittest
from unittest.mock import Mock, patch

from core import bitdoglab_serial_client as client


INICIO = (
    "JOYSTICK_INICIO,protocolo=2,modelo=TRAJETORIAS_2D,periodo_ms=20,"
    "limite_ms=90000,tolerancia_u=0.140,forca_controlada=0,clinico=0"
)
FINAL = "JOYSTICK_FINAL,protocolo=2,concluidas=3,total=3,clinico=0"
IDLE = "Aguardando botao A (teste do joystick) ou B (oximetro)..."


def resultado(forma="QUADRADO", estado="CONCLUIDO", progresso=100, valido=1):
    return (
        f"JOYSTICK_RESULTADO,forma={forma},estado={estado},progresso={progresso},"
        f"amostras=101,valido={valido},tempo_ms=2000,caminho_u=6.00000,"
        "vel_media_u_s=3.00000,acel_media_u_s2=0.50000,desvio_medio_u=0.01000,"
        "rmse_u=0.02000,sobreposicao_pct=99.50,npv=12,maior_intervalo_ms=21,"
        "area=NA,clinico=0"
    )


def posicao(**overrides):
    fields = {
        "forma": "QUADRADO", "fase": "PERCURSO", "t_ms": 120,
        "x": -0.50, "y": 0.75, "alvo_x": -0.375, "alvo_y": 0.75,
        "passo": 3, "progresso": 4,
    }
    fields.update(overrides)
    return "JOYSTICK_POSICAO," + ",".join(f"{key}={value}" for key, value in fields.items())


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.results = []
        self.samples = []
        self.lines = []
        self.connections = []
        self.positions = []
        self.reader = client.JoystickTestSerialReader(
            "COM_TEST", on_line=self.lines.append, on_result=self.results.append,
            on_sample=self.samples.append, on_connection=self.connections.append,
            on_position=self.positions.append,
        )

    def feed(self, *lines):
        for line in lines:
            self.reader._parse_linha(line)

    def test_complete_session_follows_board_and_preserves_typed_metrics(self):
        self.feed(INICIO)
        self.assertEqual(self.results[-1]["estado"], "CALIBRANDO")
        self.assertEqual(self.results[-1]["configuracao"]["periodo_ms"], 20)
        self.feed("JOYSTICK_CALIBRACAO,centro_x=2048,centro_y=2050")
        self.assertEqual(self.results[-1]["estado"], "PRONTO")
        for shape in client.FORMAS:
            self.feed(f"JOYSTICK_ETAPA,forma={shape},fase=POSICIONAR")
            self.assertEqual(self.results[-1]["estado"], "POSICIONAR")
            self.feed(f"JOYSTICK_ETAPA,forma={shape},fase=PERCURSO")
            self.assertEqual(self.results[-1]["estado"], "PERCURSO")
            self.feed(resultado(shape))
            self.assertEqual(self.results[-1]["estado"], "RESULTADO")
        self.feed(FINAL)
        snapshot = self.results[-1]
        self.assertEqual(snapshot["estado"], "FINALIZADO")
        self.assertEqual(snapshot["final"]["concluidas"], 3)
        self.assertEqual(set(snapshot["resultados"]), set(client.FORMAS))
        square = snapshot["resultados"]["QUADRADO"]
        self.assertEqual(square["tempo_ms"], 2000)
        self.assertEqual(square["sobreposicao_pct"], 99.5)
        self.assertEqual(square["npv"], 12)
        self.assertEqual(square["area"], "NA")
        self.assertEqual(square["clinico"], 0)
        self.assertNotIn("joystick_falhou", snapshot)

    def test_partial_and_not_started_are_different_from_numeric_validity(self):
        self.feed(INICIO, resultado(estado="TEMPO_LIMITE", progresso=37))
        self.assertEqual(self.results[-1]["resultados"]["QUADRADO"]["valido"], 1)
        self.assertEqual(self.results[-1]["resultados"]["QUADRADO"]["progresso"], 37)
        line = resultado("TRIANGULO", "NAO_INICIADO", 0, 0)
        line = line.replace("amostras=101", "amostras=0").replace("tempo_ms=2000", "tempo_ms=0")
        self.feed(line, FINAL.replace("concluidas=3", "concluidas=0"))
        self.assertEqual(self.results[-1]["final"]["concluidas"], 0)
        self.assertEqual(self.results[-1]["resultados"]["TRIANGULO"]["valido"], 0)

    def test_next_start_resets_results_and_does_not_mutate_old_snapshots(self):
        self.feed(INICIO, resultado(), FINAL)
        previous = self.results[-1]
        self.feed(INICIO)
        self.assertEqual(self.results[-1]["resultados"], {})
        self.assertIsNone(self.results[-1]["final"])
        self.assertIn("QUADRADO", previous["resultados"])
        previous["resultados"]["QUADRADO"]["npv"] = 999
        self.feed(resultado())
        self.assertEqual(self.reader.resultados["QUADRADO"]["npv"], 12)
        self.results[-1]["configuracao"]["limite_ms"] = 1
        self.assertEqual(self.reader.configuracao["limite_ms"], 90000)

    def test_cancel_before_final_and_idle_preserve_partial_results(self):
        self.feed(INICIO, resultado(), "JOYSTICK_CANCELADO", IDLE)
        self.assertEqual(self.results[-1]["estado"], "CANCELADO")
        self.assertIsNone(self.results[-1]["final"])
        self.assertIn("QUADRADO", self.results[-1]["resultados"])

    def test_cancel_after_final_does_not_invalidate_completed_session(self):
        self.feed(INICIO, resultado(), FINAL, "JOYSTICK_CANCELADO", IDLE)
        self.assertEqual(self.results[-1]["estado"], "FINALIZADO")
        self.assertEqual(self.results[-1]["final"]["concluidas"], 3)

    def test_calibration_error_survives_idle_and_can_be_retried(self):
        self.feed(INICIO, "JOYSTICK_ERRO,motivo=CALIBRACAO,centro_x=4095,centro_y=2048,ruido_x=0,ruido_y=200", IDLE)
        self.assertEqual(self.results[-1]["estado"], "ERRO")
        self.assertEqual(self.results[-1]["calibracao"]["ruido_y"], 200)
        self.assertIsNone(self.results[-1]["final"])
        self.feed(INICIO)
        self.assertEqual(self.results[-1]["estado"], "CALIBRANDO")
        self.assertEqual(self.results[-1]["calibracao"], {})

    def test_mid_session_connection_accepts_stage_without_inventing_configuration(self):
        self.feed("JOYSTICK_ETAPA,forma=TRIANGULO,fase=PERCURSO")
        self.assertEqual(self.results[-1]["protocolo"], 2)
        self.assertEqual(self.results[-1]["configuracao"], {})
        self.assertEqual(self.results[-1]["forma_atual"], "TRIANGULO")

    def test_unsupported_version_blocks_records_until_supported_start(self):
        self.feed(INICIO.replace("protocolo=2", "protocolo=3"))
        self.assertEqual(self.results[-1]["estado"], "ERRO")
        count = len(self.results)
        self.feed(resultado(), FINAL)
        self.assertEqual(len(self.results), count)
        self.feed(INICIO, resultado())
        self.assertEqual(self.results[-1]["estado"], "RESULTADO")
        self.assertEqual(self.results[-1]["protocolo"], 2)

    def test_bad_records_are_ignored_without_partial_state_changes(self):
        self.feed(INICIO)
        invalid = [
            "JOYSTICK_ETAPA,forma=QUADRADO,fase=INVALIDA",
            "JOYSTICK_ETAPA,forma=UNKNOWN,fase=PERCURSO",
            "JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO,fase=POSICIONAR",
            "JOYSTICK_CALIBRACAO,centro_x=2048,centro_y=broken",
            "JOYSTICK_RESULTADO,forma=QUADRADO,estado=CONCLUIDO",
            resultado().replace("rmse_u=0.02000", "rmse_u=nan"),
            resultado().replace("caminho_u=6.00000", "caminho_u=inf"),
            resultado().replace("progresso=100", "progresso=101"),
            resultado().replace("tempo_ms=2000", "tempo_ms=-1"),
            resultado().replace("clinico=0", "clinico=1"),
            FINAL.replace("concluidas=3", "concluidas=4"),
            "JOYSTICK_AMOSTRA,forma=CIRCULO,t_ms=20,x=nan,y=0",
            "JOYSTICK_AMOSTRA,forma=CIRCULO,t_ms=20,x=1.5,y=0",
            "JOYSTICK_ERRO,motivo=CALIBRACAO,ruido_y=broken",
            "JOYSTICK_EVENTO_DESCONHECIDO,campo=0",
            "OXI_FINAL,fc=72.0,spo2=98.0",
            "== Teste: DIREITA ==",
        ]
        for line in invalid:
            with self.subTest(line=line):
                self.feed(line)
                self.assertEqual(len(self.results), 1)
                self.assertEqual(self.reader.estado, "CALIBRANDO")
                self.assertEqual(self.reader.resultados, {})
                self.assertEqual(self.reader.calibracao, {})
                self.assertEqual(self.samples, [])

    def test_optional_samples_have_separate_callback_after_result(self):
        self.feed(INICIO, resultado())
        count = len(self.results)
        self.feed("JOYSTICK_AMOSTRA,forma=QUADRADO,t_ms=20,x=-0.75000,y=0.75000")
        self.assertEqual(self.samples, [{"forma": "QUADRADO", "t_ms": 20, "x": -0.75, "y": 0.75}])
        self.assertEqual(len(self.results), count)
        self.assertEqual(self.reader.estado, "RESULTADO")

    def test_live_positions_use_separate_typed_callback_without_result_snapshots(self):
        self.feed(INICIO + ",telemetria_ms=50", "JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO")
        result_count = len(self.results)
        self.feed(posicao(), posicao(t_ms=170, x=-0.25, passo=4, progresso=6))
        self.assertEqual(self.positions, [
            {"forma": "QUADRADO", "fase": "PERCURSO", "t_ms": 120,
             "x": -0.5, "y": 0.75, "alvo_x": -0.375, "alvo_y": 0.75,
             "passo": 3, "progresso": 4},
            {"forma": "QUADRADO", "fase": "PERCURSO", "t_ms": 170,
             "x": -0.25, "y": 0.75, "alvo_x": -0.375, "alvo_y": 0.75,
             "passo": 4, "progresso": 6},
        ])
        self.assertEqual(len(self.results), result_count)
        self.assertEqual(self.reader.resultados, {})
        self.assertIsNone(self.reader.final)
        self.assertEqual(self.samples, [])

    def test_live_timestamps_increase_per_phase_and_restart_at_next_phase(self):
        self.feed(INICIO, "JOYSTICK_ETAPA,forma=QUADRADO,fase=POSICIONAR")
        self.feed(posicao(fase="POSICIONAR", t_ms=1200, passo=0, progresso=0))
        self.feed(posicao(fase="POSICIONAR", t_ms=1190), posicao(fase="POSICIONAR", t_ms=1200))
        self.assertEqual(len(self.positions), 1)
        self.feed("JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO", posicao(t_ms=0))
        self.feed(posicao(t_ms=50), posicao(t_ms=0), posicao(fase="POSICIONAR", t_ms=1300))
        self.assertEqual([p["t_ms"] for p in self.positions], [1200, 0, 50])
        self.feed("JOYSTICK_ETAPA,forma=TRIANGULO,fase=POSICIONAR")
        self.feed(posicao(forma="TRIANGULO", fase="POSICIONAR", t_ms=0, passo=0, progresso=0))
        self.assertEqual(len(self.positions), 4)
        self.assertEqual(self.positions[-1]["forma"], "TRIANGULO")

    def test_live_frames_cannot_change_known_shape_or_phase(self):
        self.feed(INICIO, posicao())
        self.assertEqual(self.reader.estado, "CALIBRANDO")
        self.feed("JOYSTICK_CALIBRACAO,centro_x=2048,centro_y=2048", posicao())
        self.assertEqual(self.reader.estado, "PRONTO")
        self.feed("JOYSTICK_ETAPA,forma=QUADRADO,fase=POSICIONAR")
        self.feed(posicao(), posicao(forma="CIRCULO", fase="POSICIONAR"))
        self.assertEqual(self.reader.estado, "POSICIONAR")
        self.assertEqual(self.positions, [])
        self.feed(resultado(), posicao(t_ms=200), IDLE, posicao(t_ms=250))
        self.assertEqual(self.positions, [])
        self.assertEqual(self.reader.estado, "AGUARDANDO")

    def test_first_live_frame_can_attach_mid_phase_without_repeated_snapshots(self):
        order = []
        self.reader.on_result = lambda snapshot: (self.results.append(snapshot), order.append("stage"))
        self.reader.on_position = lambda position: (self.positions.append(position), order.append("position"))
        self.feed(IDLE)
        self.results.clear()
        order.clear()
        self.feed(posicao(forma="TRIANGULO", t_ms=800), posicao(forma="TRIANGULO", t_ms=850))
        self.assertEqual(order, ["stage", "position", "position"])
        self.assertEqual(len(self.results), 1)
        self.assertEqual(self.results[0]["forma_atual"], "TRIANGULO")
        self.assertEqual(self.results[0]["estado"], "PERCURSO")
        self.assertEqual(self.results[0]["protocolo"], 2)
        self.assertEqual(self.results[0]["configuracao"], {})
        self.assertEqual(self.results[0]["resultados"], {})

    def test_terminal_events_block_live_frames_until_new_valid_start(self):
        for event in (FINAL, "JOYSTICK_CANCELADO", "JOYSTICK_ERRO,motivo=CALIBRACAO"):
            with self.subTest(event=event):
                self.reader.reset()
                self.positions.clear()
                self.feed(INICIO, "JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO", posicao())
                self.feed(event, posicao(t_ms=170))
                # A stray phase event must not resurrect telemetry of a closed session.
                self.feed("JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO", posicao(t_ms=220))
                self.assertEqual(len(self.positions), 1)
                self.feed(INICIO, "JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO", posicao(t_ms=0))
                self.assertEqual(len(self.positions), 2)
                self.assertEqual(self.positions[-1]["t_ms"], 0)

    def test_malformed_live_frames_do_not_change_phase_or_timestamp(self):
        invalid = [
            posicao(forma="DESCONHECIDA"), posicao(fase="FINALIZADO"),
            posicao(t_ms=-1), posicao(t_ms=0x100000000), posicao(t_ms="12.5"),
            posicao(x="nan"), posicao(y="inf"), posicao(alvo_x="-inf"), posicao(alvo_y="NaN"),
            posicao(x=-1.01), posicao(y=1.01), posicao(alvo_x=1.01), posicao(alvo_y=-1.01),
            posicao(passo=49), posicao(passo=-1), posicao(progresso=101), posicao(progresso=-1),
            posicao().replace(",alvo_y=0.75", ""), posicao() + ",x=0",
        ]
        for line in invalid:
            with self.subTest(line=line):
                self.feed(line)
                self.assertEqual(self.reader.estado, "AGUARDANDO")
                self.assertEqual(self.results, [])
                self.assertEqual(self.positions, [])
        self.feed(posicao(t_ms=0, x=-1, y=1, alvo_x=1, alvo_y=-1, passo=48, progresso=100))
        self.assertEqual(len(self.positions), 1)
        self.feed(posicao(t_ms=20, x="nan"), posicao(t_ms=10))
        self.assertEqual([p["t_ms"] for p in self.positions], [0, 10])

    def test_telemetry_configuration_is_optional_and_validated_atomically(self):
        self.feed(INICIO)
        self.assertNotIn("telemetria_ms", self.results[-1]["configuracao"])
        self.feed(INICIO + ",telemetria_ms=50")
        self.assertEqual(self.results[-1]["configuracao"]["telemetria_ms"], 50)
        snapshot_count = len(self.results)
        for value in ("0", "-1", "nan", "50.0", "4294967296"):
            self.feed(INICIO + f",telemetria_ms={value}")
            self.assertEqual(len(self.results), snapshot_count)
            self.assertEqual(self.reader.configuracao["telemetria_ms"], 50)
        self.feed(INICIO, "JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO", resultado(), FINAL)
        self.assertEqual(self.reader.estado, "FINALIZADO")
        self.assertEqual(self.positions, [])

    def test_live_frame_fragments_emit_once_only_after_complete_line(self):
        frame = (posicao() + "\r\n").encode()
        self.reader._consume_chunk(frame[:40])
        self.reader._consume_chunk(b"")
        self.assertEqual(self.positions, [])
        self.assertEqual(self.results, [])
        self.reader._consume_chunk(frame[40:-1])
        self.assertEqual(self.positions, [])
        self.reader._consume_chunk(frame[-1:] + (posicao(t_ms=170) + "\n").encode())
        self.assertEqual([p["t_ms"] for p in self.positions], [120, 170])
        self.assertEqual(len(self.results), 1)
        self.assertEqual(len(self.lines), 2)

    def test_timeout_fragments_and_multiple_lines_are_reassembled(self):
        wire = (INICIO + "\r\nJOYSTICK_CALIBRACAO,centro_x=2048,centro_y=2048\n").encode()
        self.reader._consume_chunk(wire[:31])
        self.reader._consume_chunk(b"")
        self.assertEqual(self.results, [])
        self.reader._consume_chunk(wire[31:])
        self.assertEqual([s["estado"] for s in self.results], ["CALIBRANDO", "PRONTO"])
        self.assertEqual(len(self.lines), 2)

    def test_oversized_noise_is_dropped_and_next_record_recovers(self):
        self.reader._consume_chunk(b"x" * (client._MAX_LINE_BYTES + 1))
        self.assertEqual(len(self.reader._pending), 0)
        self.reader._consume_chunk(("ignored\n" + INICIO + "\n").encode())
        self.assertEqual(self.lines, [INICIO])
        self.assertEqual(self.reader.estado, "CALIBRANDO")

    def test_missing_dependency_and_open_failure_are_reported(self):
        with patch.object(client, "serial", None):
            self.reader.start()
        self.assertEqual(self.connections[-1]["estado"], "ERRO")
        fake_serial = Mock()
        fake_serial.Serial.side_effect = OSError("Porta ocupada")
        with patch.object(client, "serial", fake_serial):
            self.reader._run()
        self.assertEqual(self.connections[-1]["estado"], "ERRO")
        self.assertIn("Porta ocupada", self.connections[-1]["mensagem"])

    def test_usb_failure_closes_port_and_keeps_error_as_last_connection_event(self):
        connection = Mock()
        connection.readline.side_effect = [INICIO.encode() + b"\n", OSError("USB removido")]
        fake_serial = Mock()
        fake_serial.Serial.return_value = connection
        with patch.object(client, "serial", fake_serial):
            self.reader._run()
        self.assertEqual([s["estado"] for s in self.connections], ["CONECTADO", "ERRO"])
        connection.close.assert_called_once()
        self.assertIsNone(self.reader._ser)
        self.assertEqual(self.results[-1]["estado"], "CALIBRANDO")

    def test_normal_stop_closes_port_and_reports_disconnection(self):
        connection = Mock()
        connection.readline.return_value = INICIO.encode() + b"\n"
        fake_serial = Mock()
        fake_serial.Serial.return_value = connection
        self.reader.on_result = lambda snapshot: self.reader._stop.set()
        with patch.object(client, "serial", fake_serial):
            self.reader._run()
        self.assertEqual([s["estado"] for s in self.connections], ["CONECTADO", "DESCONECTADO"])
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
