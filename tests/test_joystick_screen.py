"""Integration checks for the firmware protocol and the desktop joystick screen."""

import os
import threading
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.bitdoglab_serial_client import JoystickTestSerialReader
from screens.joystick_test_screen import JoystickTestScreen


START = (
    "JOYSTICK_INICIO,protocolo=2,modelo=TRAJETORIAS_2D,periodo_ms=20,"
    "limite_ms=90000,tolerancia_u=0.140,forca_controlada=0,clinico=0"
)
LIVE_START = START + ",telemetria_ms=50"


def position_line(phase="PERCURSO", t=60, x=-0.5, progress=4):
    return (
        f"JOYSTICK_POSICAO,forma=QUADRADO,fase={phase},t_ms={t},x={x},y=0.75,"
        f"alvo_x=-0.375,alvo_y=0.75,passo={3 if phase == 'PERCURSO' else 0},"
        f"progresso={progress if phase == 'PERCURSO' else 0}"
    )


def result_line(shape, state="CONCLUIDO", progress=100, valid=1):
    samples = 200 if state != "NAO_INICIADO" else 0
    metrics = (
        "tempo_ms=3980,caminho_u=5.85000,vel_media_u_s=1.46985,"
        "acel_media_u_s2=0.25000,desvio_medio_u=0.02000,rmse_u=0.03000,"
        "sobreposicao_pct=96.50,npv=50,maior_intervalo_ms=22"
        if samples else
        "tempo_ms=0,caminho_u=0.00000,vel_media_u_s=0.00000,"
        "acel_media_u_s2=0.00000,desvio_medio_u=0.00000,rmse_u=0.00000,"
        "sobreposicao_pct=0.00,npv=0,maior_intervalo_ms=0"
    )
    return (
        f"JOYSTICK_RESULTADO,forma={shape},estado={state},progresso={progress},"
        f"amostras={samples},valido={valid},{metrics},area=NA,clinico=0"
    )


class JoystickScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.on_finish = Mock()
        self.initial_model = Mock()
        self.initial_model.model = object()
        self.initial_model.metadata = {"data_kind": "synthetic", "label_provenance": "synthetic_rules"}
        self.initial_model.load_error = None
        with patch("screens.joystick_test_screen.load_app_model", return_value=self.initial_model) as loader:
            self.screen = JoystickTestScreen(self.on_finish)
        self.model_loader = loader
        self.screen.reader = Mock()
        self.token = self.screen._session_id
        self.parser = JoystickTestSerialReader(
            port="TEST",
            on_result=lambda data: self.screen._apply_update(self.token, data),
            on_sample=lambda data: self.screen._apply_sample(self.token, data),
            on_position=lambda data: self.screen._apply_position(self.token, data),
        )

    def tearDown(self):
        self.screen.leave_screen()
        self.screen.close()
        self.screen.deleteLater()
        self.app.processEvents()

    def feed(self, *lines):
        for line in lines:
            self.parser._parse_linha(line)

    def complete(self, states=None):
        self.feed(START, "JOYSTICK_CALIBRACAO,centro_x=2048,centro_y=2050")
        states = states or ["CONCLUIDO"] * 3
        shapes = ("QUADRADO", "TRIANGULO", "CIRCULO")
        for shape, state in zip(shapes, states):
            self.feed(f"JOYSTICK_ETAPA,forma={shape},fase=POSICIONAR")
            if state != "NAO_INICIADO":
                self.feed(f"JOYSTICK_ETAPA,forma={shape},fase=PERCURSO")
            progress = {"CONCLUIDO": 100, "TEMPO_LIMITE": 50, "NAO_INICIADO": 0}[state]
            self.feed(result_line(shape, state, progress, int(state != "NAO_INICIADO")))
        self.feed(
            f"JOYSTICK_FINAL,protocolo=2,concluidas={states.count('CONCLUIDO')},total=3,clinico=0"
        )

    def test_complete_protocol_enables_finish_only_after_final(self):
        self.assertFalse(self.screen.finish_btn.isEnabled())
        self.feed(START, "JOYSTICK_CALIBRACAO,centro_x=2048,centro_y=2050")
        for shape in ("QUADRADO", "TRIANGULO", "CIRCULO"):
            self.feed(f"JOYSTICK_ETAPA,forma={shape},fase=POSICIONAR")
            self.assertEqual(self.screen._ultimo_resultado["estado"], "POSICIONAR")
            self.feed(f"JOYSTICK_ETAPA,forma={shape},fase=PERCURSO")
            self.assertEqual(self.screen._ultimo_resultado["forma_atual"], shape)
            self.feed(result_line(shape))
            self.assertFalse(self.screen.finish_btn.isEnabled())
        self.feed("JOYSTICK_FINAL,protocolo=2,concluidas=3,total=3,clinico=0")
        self.assertTrue(self.screen.finish_btn.isEnabled())
        self.assertEqual(len(self.screen._ultimo_resultado["resultados"]), 3)
        self.assertEqual(self.screen.results_table.rowCount(), 3)

    def test_final_result_survives_mode_switch_and_idle(self):
        self.complete()
        self.feed("JOYSTICK_CANCELADO", "OXI_INICIO", "Aguardando botao A (teste do joystick) ou B (oximetro)...")
        self.assertTrue(self.screen.finish_btn.isEnabled())
        self.assertEqual(self.screen._ultimo_resultado["final"]["concluidas"], 3)

    def test_calibration_error_and_cancel_do_not_complete_session(self):
        self.feed(START, "JOYSTICK_ERRO,motivo=CALIBRACAO,centro_x=900,centro_y=2048,ruido_x=200,ruido_y=10")
        self.assertFalse(self.screen.finish_btn.isEnabled())
        self.assertEqual(self.screen._ultimo_resultado["estado"], "ERRO")
        self.feed(START, "JOYSTICK_CALIBRACAO,centro_x=2048,centro_y=2050")
        self.feed("JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO", "JOYSTICK_CANCELADO")
        self.assertFalse(self.screen.finish_btn.isEnabled())
        self.assertEqual(self.screen._ultimo_resultado["estado"], "CANCELADO")

    def test_new_start_removes_previous_results_and_exported_path(self):
        self.feed(START)
        for shape in ("QUADRADO", "TRIANGULO", "CIRCULO"):
            self.feed(result_line(shape))
        self.feed("JOYSTICK_AMOSTRA,forma=CIRCULO,t_ms=0,x=0.0,y=0.75")
        self.feed("JOYSTICK_FINAL,protocolo=2,concluidas=3,total=3,clinico=0")
        self.assertEqual(len(self.screen._samples["CIRCULO"]), 1)
        self.feed(START)
        self.assertFalse(self.screen.finish_btn.isEnabled())
        self.assertEqual(self.screen._ultimo_resultado["resultados"], {})
        self.assertTrue(all(not samples for samples in self.screen._samples.values()))

    def test_stale_session_callbacks_cannot_replace_current_data(self):
        self.complete()
        before = self.screen._ultimo_resultado
        self.screen._apply_update(self.token - 1, {"estado": "CALIBRANDO", "resultados": {}, "final": None})
        self.screen._apply_sample(self.token - 1, {"forma": "QUADRADO", "t_ms": 0, "x": 0, "y": 0})
        self.screen._apply_connection(self.token - 1, {"estado": "ERRO", "mensagem": "Porta antiga"})
        self.assertIs(self.screen._ultimo_resultado, before)
        self.assertTrue(self.screen.finish_btn.isEnabled())
        self.assertTrue(all(not samples for samples in self.screen._samples.values()))

    def test_connection_failure_is_visible_and_allows_retry(self):
        self.screen._apply_connection(self.token, {"estado": "ERRO", "mensagem": "Porta COM5 indisponível"})
        self.assertIsNone(self.screen.reader)
        self.assertEqual(self.screen.connect_btn.text(), "Conectar")
        self.assertIn("COM5", self.screen.connection_label.text())
        self.assertFalse(self.screen.finish_btn.isEnabled())

    def test_connect_waits_for_serial_confirmation(self):
        self.screen.reader = None
        self.screen.port_input.setText("COM_TEST")
        with patch("screens.joystick_test_screen.JoystickTestSerialReader") as reader_factory:
            self.screen._connect()
            self.assertIn("Conectando", self.screen.connection_label.text())
            self.assertFalse(self.screen.port_input.isEnabled())
            reader_factory.return_value.start.assert_called_once_with()
            callbacks = reader_factory.call_args.kwargs
            self.assertEqual(callbacks["port"], "COM_TEST")
            callbacks["on_connection"]({"estado": "CONECTADO", "mensagem": "Conectado"})
            self.assertIn("Conectando", self.screen.connection_label.text())
            self.app.processEvents()
            self.assertIn("Conectado", self.screen.connection_label.text())
            self.assertIn("COM_TEST", self.screen.connection_label.text())

    def test_missing_metrics_are_not_displayed_as_perfect_zero_values(self):
        self.complete(["CONCLUIDO", "TEMPO_LIMITE", "NAO_INICIADO"])
        table = self.screen.results_table
        self.assertIn("parcial", table.item(1, 1).text())
        self.assertEqual(table.item(1, 2).text(), "50%")
        self.assertEqual(table.item(1, 3).text(), "3.98")
        self.assertEqual(table.item(2, 1).text(), "Não iniciado")
        self.assertEqual(table.item(2, 2).text(), "0%")
        for column in (3, 4, 5):
            self.assertEqual(table.item(2, column).text(), "—")
        self.assertEqual(table.item(2, 6).text(), "Sem métricas")

    def test_finish_without_final_does_not_call_model(self):
        self.screen.risco_model = Mock()
        with patch("screens.joystick_test_screen.QMessageBox.warning"):
            self.screen._finish()
        self.screen.risco_model.predict.assert_not_called()
        self.on_finish.assert_not_called()

    def test_model_factory_and_experimental_status_are_visible(self):
        self.model_loader.assert_called_once_with()
        self.assertIs(self.screen.risco_model, self.initial_model)
        status = self.screen.model_status_label.text().lower()
        self.assertIn("experimental", status)
        self.assertIn("sintéticos", status)
        self.assertFalse(self.screen.model_status_label.isHidden())

    def measured_stages(self, *, arm_ratio=0.2, side=0, face=0, bpm=80.0, spo2=98.0):
        self.screen._pretriagem_screen = Mock()
        self.screen._pretriagem_screen.port_input.text.return_value = "TEST"
        self.screen._pretriagem_screen.get_vitals.return_value = {"heart_rate": bpm, "spo2": spo2}
        self.screen._arm_test_screen = Mock()
        self.screen._arm_test_screen.get_features.return_value = {
            "arm_ratio": arm_ratio, "arm_weak_side_code": side,
        }
        self.screen._facial_screen = Mock()
        self.screen._facial_screen.get_features.return_value = {"facial_asymmetry_score": face}

    def test_finish_sends_result_snapshot_and_calls_model_once_without_popup(self):
        self.complete()
        self.measured_stages(face=1)
        self.screen.risco_model.predict.return_value = {
            "risco": "DEMO_SINAL_MOTOR", "confianca": 0.9,
            "probabilidades": {"DEMO_SINAL_MOTOR": 0.9},
            "aviso": "DEMONSTRAÇÃO SINTÉTICA — não estima presença ou ausência de AVC.",
        }
        with patch("screens.joystick_test_screen.QMessageBox.information") as message:
            self.screen._finish()
        self.screen.risco_model.predict.assert_called_once()
        message.assert_not_called()
        self.on_finish.assert_called_once()
        payload = self.on_finish.call_args.args[0]
        self.assertEqual(payload["veredito"], self.screen.risco_model.predict.return_value)
        self.assertEqual(payload["features"]["facial_asymmetry_score"], 1)
        self.assertEqual(payload["joystick"]["final"]["concluidas"], 3)
        self.assertIn("sintéticos", payload["model_status"])
        self.assertIsNotNone(datetime.fromisoformat(payload["generated_at"]).tzinfo)
        self.assertIsNone(self.screen.reader)
        self.assertFalse(self.screen.finish_btn.isEnabled())

    def test_prediction_is_forwarded_without_replacing_it_with_reference_rule(self):
        self.complete()
        self.measured_stages(face=2)
        self.screen.risco_model.predict.return_value = {
            "risco": "DEMO_SEM_REGRA_ACIONADA", "aviso": None,
        }
        self.screen._finish()
        payload = self.on_finish.call_args.args[0]
        self.assertEqual(payload["veredito"]["risco"], "DEMO_SEM_REGRA_ACIONADA")
        self.assertEqual(payload["features"]["facial_asymmetry_score"], 2)

    def test_missing_bpm_remains_explicit_even_if_model_does_not_predict_incomplete_class(self):
        self.complete()
        self.measured_stages(bpm=0.0)
        self.screen.risco_model.predict.return_value = {
            "risco": "DEMO_SEM_REGRA_ACIONADA", "aviso": None,
        }
        self.screen._finish()
        payload = self.on_finish.call_args.args[0]
        self.assertIsNone(payload["features"]["heart_rate"])
        self.assertEqual(payload["veredito"]["risco"], "DEMO_SEM_REGRA_ACIONADA")
        self.assertIsNone(self.screen.risco_model.predict.call_args.args[0]["heart_rate"])

    def test_partial_and_not_started_results_do_not_become_weakness_feature(self):
        self.complete(["CONCLUIDO", "TEMPO_LIMITE", "NAO_INICIADO"])
        self.assertTrue(self.screen.finish_btn.isEnabled())
        self.screen._pretriagem_screen = Mock()
        self.screen._pretriagem_screen.get_vitals.return_value = {"heart_rate": 73.0, "spo2": 97.0}
        self.screen._facial_screen = Mock()
        self.screen._facial_screen.get_features.return_value = {"facial_asymmetry_score": 1}
        self.screen._arm_test_screen = Mock()
        self.screen._arm_test_screen.get_features.return_value = {"arm_ratio": 0.8, "arm_weak_side_code": 1}
        self.screen.risco_model = Mock()
        self.screen.risco_model.predict.return_value = {"risco": "indefinido", "aviso": None}
        self.screen._finish()
        self.screen.risco_model.predict.assert_called_once_with({
            "arm_ratio": 0.8,
            "arm_weak_side_code": 1,
            "facial_asymmetry_score": 1,
            "heart_rate": 73.0,
            "spo2": 97.0,
        })
        self.on_finish.assert_called_once()
        payload = self.on_finish.call_args.args[0]
        self.assertEqual(payload["features"], self.screen.risco_model.predict.call_args.args[0])
        self.assertEqual(payload["joystick"]["final"]["concluidas"], 1)
        self.assertEqual(payload["joystick"]["resultados"]["TRIANGULO"]["estado"], "TEMPO_LIMITE")
        self.assertEqual(payload["joystick"]["resultados"]["CIRCULO"]["estado"], "NAO_INICIADO")

    def test_unmeasured_stages_remain_missing_at_inference(self):
        self.complete()
        self.screen._pretriagem_screen = Mock()
        self.screen._pretriagem_screen.get_vitals.return_value = {"heart_rate": 0.0, "spo2": 0.0}
        self.screen.risco_model = Mock()
        self.screen.risco_model.predict.return_value = {"risco": "indefinido", "aviso": "Sem medições."}
        self.screen._finish()
        self.screen.risco_model.predict.assert_called_once_with({
            "arm_ratio": None, "arm_weak_side_code": None,
            "facial_asymmetry_score": None, "heart_rate": None, "spo2": None,
        })
        payload = self.on_finish.call_args.args[0]
        self.assertEqual(payload["veredito"]["aviso"], "Sem medições.")
        self.assertTrue(all(value is None for value in payload["features"].values()))

    def test_valid_zero_observations_are_preserved(self):
        self.complete()
        self.screen._facial_screen = Mock()
        self.screen._facial_screen.get_features.return_value = {"facial_asymmetry_score": 0}
        self.screen._arm_test_screen = Mock()
        self.screen._arm_test_screen.get_features.return_value = {"arm_ratio": 0.0, "arm_weak_side_code": 0}
        self.screen.risco_model = Mock()
        self.screen.risco_model.predict.return_value = {"risco": "indefinido", "aviso": None}
        self.screen._finish()
        features = self.screen.risco_model.predict.call_args.args[0]
        self.assertEqual(features["arm_ratio"], 0.0)
        self.assertEqual(features["arm_weak_side_code"], 0)
        self.assertEqual(features["facial_asymmetry_score"], 0)

    def test_final_snapshot_does_not_follow_mutations_in_measurements_or_results(self):
        self.complete()
        self.measured_stages(face=1)
        verdict = {"risco": "DEMO_SINAL_MOTOR", "probabilidades": {"DEMO_SINAL_MOTOR": 0.9}}
        self.screen.risco_model.predict.return_value = verdict
        self.screen._finish()
        payload = self.on_finish.call_args.args[0]
        verdict["probabilidades"]["DEMO_SINAL_MOTOR"] = 0.1
        self.screen.risco_model.predict.call_args.args[0]["heart_rate"] = 150
        self.screen._ultimo_resultado["final"]["concluidas"] = 0
        self.screen._ultimo_resultado["resultados"]["QUADRADO"]["tempo_ms"] = 1
        self.assertEqual(payload["veredito"]["probabilidades"]["DEMO_SINAL_MOTOR"], 0.9)
        self.assertEqual(payload["features"]["heart_rate"], 80)
        self.assertEqual(payload["joystick"]["final"]["concluidas"], 3)
        self.assertEqual(payload["joystick"]["resultados"]["QUADRADO"]["tempo_ms"], 3980)

    def test_repeated_finish_is_ignored_and_new_session_can_finish_again(self):
        self.complete()
        self.measured_stages()
        self.screen.risco_model.predict.return_value = {"risco": "DEMO_SEM_REGRA_ACIONADA"}
        self.screen._finish()
        self.screen._finish()
        self.screen.finish_btn.click()
        self.screen.risco_model.predict.assert_called_once()
        self.on_finish.assert_called_once()
        self.screen.enter_screen()
        self.screen.reader = Mock()
        self.token = self.screen._session_id
        self.complete()
        self.screen._finish()
        self.assertEqual(self.screen.risco_model.predict.call_count, 2)
        self.assertEqual(self.on_finish.call_count, 2)

    def test_worker_signal_is_delivered_through_qt_event_queue(self):
        updates = []
        reader = JoystickTestSerialReader("TEST", on_result=updates.append)
        reader._parse_linha(START)
        worker = threading.Thread(target=lambda: self.screen._update_received.emit(self.token, updates[-1]))
        worker.start()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(self.screen._ultimo_resultado)
        self.app.processEvents()
        self.assertEqual(self.screen._ultimo_resultado["estado"], "CALIBRANDO")

    def test_live_position_moves_cursor_and_updates_progress_before_result(self):
        self.feed(LIVE_START, "JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO")
        with patch.object(self.screen.trajectory, "set_live_position", wraps=self.screen.trajectory.set_live_position) as draw:
            self.feed(position_line(t=0, x=-0.75, progress=0))
            self.screen._refresh_preview()
            self.assertEqual(draw.call_args.args[0]["x"], -0.75)
            self.feed(position_line(t=60, x=-0.5, progress=4))
            self.screen._refresh_preview()
            self.assertEqual(draw.call_args.args[0]["x"], -0.5)
            self.assertEqual(draw.call_args.args[0]["alvo_x"], -0.375)
        self.assertEqual(len(self.screen._live_samples["QUADRADO"]), 2)
        self.assertEqual(self.screen._ultimo_resultado["resultados"], {})
        self.assertEqual(self.screen.results_table.item(0, 2).text(), "4%")
        self.assertEqual(self.screen.results_table.item(0, 3).text(), "0.06")
        self.assertIn("Ao vivo", self.screen.preview_caption.text())
        self.assertFalse(self.screen.finish_btn.isEnabled())

    def test_positioning_does_not_pollute_path_and_time_restarts_for_course(self):
        self.feed(LIVE_START, "JOYSTICK_ETAPA,forma=QUADRADO,fase=POSICIONAR")
        self.feed(position_line("POSICIONAR", t=1500, x=0.0))
        self.assertEqual(self.screen._live_samples["QUADRADO"], [])
        self.feed("JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO", position_line(t=0, x=-0.75))
        self.assertEqual(self.screen._live_positions["QUADRADO"]["t_ms"], 0)
        self.assertEqual([s["x"] for s in self.screen._live_samples["QUADRADO"]], [-0.75])

    def test_stalled_positions_hide_live_cursor_without_inventing_movement(self):
        self.feed(LIVE_START, "JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO")
        with patch("screens.joystick_test_screen.time.monotonic", return_value=100):
            self.feed(position_line())
        with patch.object(self.screen.trajectory, "set_live_position") as draw:
            with patch("screens.joystick_test_screen.time.monotonic", return_value=102):
                self.screen._check_position_age()
            draw.assert_called_with(None)
        self.assertIn("sem atualização", self.screen.preview_caption.text())
        self.assertEqual(len(self.screen._live_samples["QUADRADO"]), 1)

    def test_legacy_firmware_waits_for_telemetry_instead_of_simulating_cursor(self):
        self.feed(START, "JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO")
        with patch.object(self.screen.trajectory, "set_live_position") as draw:
            self.screen._refresh_preview()
            draw.assert_called_with(None)
        self.assertIn("firmware", self.screen.preview_caption.text())
        self.assertEqual(self.screen._live_samples["QUADRADO"], [])

    def test_result_freezes_trace_and_new_session_clears_live_state(self):
        self.feed(LIVE_START, "JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO", position_line())
        with patch.object(self.screen.trajectory, "set_live_position") as draw:
            self.feed(result_line("QUADRADO"))
            draw.assert_called_with(None)
        self.assertEqual(self.screen.results_table.item(0, 2).text(), "100%")
        self.assertEqual(self.screen.results_table.item(0, 3).text(), "3.98")
        self.assertEqual(len(self.screen._live_samples["QUADRADO"]), 1)
        self.feed(LIVE_START)
        self.assertEqual(self.screen._live_positions, {})
        self.assertTrue(all(not points for points in self.screen._live_samples.values()))

    def test_late_position_and_disconnected_source_do_not_move_cursor(self):
        self.feed(LIVE_START, "JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO", position_line())
        last = dict(self.screen._live_positions["QUADRADO"])
        self.screen._apply_position(self.token - 1, dict(last, t_ms=100, x=0.9))
        self.assertEqual(self.screen._live_positions["QUADRADO"], last)
        with patch.object(self.screen.trajectory, "set_live_position") as draw:
            self.screen._disconnect()
            draw.assert_called_with(None)
        self.screen._apply_position(self.token, dict(last, t_ms=200, x=0.9))
        self.assertEqual(self.screen._live_positions["QUADRADO"], last)

    def test_live_position_signal_is_queued_on_ui_thread(self):
        self.feed(LIVE_START, "JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO")
        frames = []
        source = JoystickTestSerialReader("TEST", on_position=frames.append)
        source._parse_linha(position_line())
        worker = threading.Thread(target=lambda: self.screen._position_received.emit(self.token, frames[0]))
        worker.start()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.screen._live_positions, {})
        self.app.processEvents()
        self.assertEqual(self.screen._live_positions["QUADRADO"]["x"], -0.5)

    def test_partial_export_preserves_live_path_until_expected_samples_arrive(self):
        self.feed(LIVE_START, "JOYSTICK_ETAPA,forma=QUADRADO,fase=PERCURSO")
        self.feed(position_line(t=0, x=-0.75), position_line(t=60, x=-0.5))
        self.feed(result_line("QUADRADO").replace("amostras=200", "amostras=2"))
        self.feed("JOYSTICK_AMOSTRA,forma=QUADRADO,t_ms=0,x=-0.75,y=0.75")
        self.screen._refresh_preview()
        self.assertIn("parcial (1 de 2 amostras)", self.screen.preview_caption.text())
        self.assertEqual(len(self.screen.trajectory._samples), 2)
        self.feed("JOYSTICK_AMOSTRA,forma=QUADRADO,t_ms=20,x=-0.70,y=0.75")
        self.screen._refresh_preview()
        self.assertIn("completo exportado", self.screen.preview_caption.text())
        self.assertEqual(self.screen.trajectory._samples[-1], (-0.70, 0.75))


if __name__ == "__main__":
    unittest.main()
