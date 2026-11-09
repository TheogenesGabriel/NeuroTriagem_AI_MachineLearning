"""
NeuroTriagem.AI - aplicacao desktop local (estrutura base)
-----------------------------------------------------------
Fluxo de telas: Inicial -> Pre-triagem (SpO2 + BPM, BitDogLab/serial)
-> Assimetria Facial -> Teste do Braco (webcam) -> Teste do Joystick
(BitDogLab/serial) -> Classificação final. Ao concluir o joystick, o Random Forest
é executado e seu resultado permanece na tela final. O modelo demonstrativo já está em
models/random_forest_regras_experimental.joblib; BPM e SpO2 são entradas.
Esse protótipo usa dados sintéticos e não diagnostica AVC. ECG é uma etapa futura.

Toda a comunicacao com a BitDogLab e serial (USB) - nao ha WebSocket.

Como rodar:
    pip install -r requirements.txt
    python main.py

Coloque os checkpoints treinados em:
    models/best.pt                       (teste do braco)
    models/facial_asymmetry_best.pt      (assimetria facial)
O app roda sem eles, so mostra a camera crua com um aviso.
"""

import logging
import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from core.random_forest_runtime import get_model_status
from core.final_result import build_final_result

from screens.arm_test_screen import ArmTestScreen
from screens.facial_screen import FacialAsymmetryScreen
from screens.final_result_screen import FinalResultScreen
from screens.home_screen import HomeScreen
from screens.joystick_test_screen import JoystickTestScreen
from screens.pretriagem_screen import PreTriagemScreen

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NeuroTriagem.AI")
        self.resize(1000, 750)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home_screen = HomeScreen(on_start=self.go_to_pretriagem)
        self.pretriagem_screen = PreTriagemScreen(on_next=self.go_to_facial, on_back=self.go_to_home)
        self.facial_screen = FacialAsymmetryScreen(on_next=self.go_to_arm_test, on_back=self.go_to_home)
        self.arm_test_screen = ArmTestScreen(on_next=self.go_to_joystick_test)
        self.final_result_screen = FinalResultScreen(
            on_new_assessment=self.go_to_pretriagem, on_home=self.go_to_home,
        )
        self.joystick_test_screen = JoystickTestScreen(
            on_finish=self.go_to_result,
            pretriagem_screen=self.pretriagem_screen,
            facial_screen=self.facial_screen,
            arm_test_screen=self.arm_test_screen,
        )
        self.home_screen.set_model_status(get_model_status(self.joystick_test_screen.risco_model))

        self.stack.addWidget(self.home_screen)            # index 0
        self.stack.addWidget(self.pretriagem_screen)       # index 1
        self.stack.addWidget(self.facial_screen)           # index 2
        self.stack.addWidget(self.arm_test_screen)         # index 3
        self.stack.addWidget(self.joystick_test_screen)    # index 4
        self.stack.addWidget(self.final_result_screen)     # index 5
        self.stack.setCurrentIndex(0)

    def go_to_pretriagem(self):
        self.final_result_screen.clear_result()
        self.pretriagem_screen.leave_screen()
        self.facial_screen.stop_camera()
        self.arm_test_screen.stop_camera()
        self.joystick_test_screen.leave_screen()
        self.pretriagem_screen.enter_screen()
        self.stack.setCurrentIndex(1)

    def go_to_facial(self):
        self.pretriagem_screen.leave_screen()  # libera a porta serial
        self.facial_screen.start_camera()
        self.stack.setCurrentIndex(2)

    def go_to_arm_test(self):
        self.facial_screen.stop_camera()
        self.arm_test_screen.start_camera()
        self.stack.setCurrentIndex(3)

    def go_to_joystick_test(self):
        self.arm_test_screen.stop_camera()
        self.joystick_test_screen.enter_screen()
        self.stack.setCurrentIndex(4)

    def go_to_home(self):
        self.pretriagem_screen.leave_screen()
        self.facial_screen.stop_camera()
        self.arm_test_screen.stop_camera()
        self.joystick_test_screen.leave_screen()
        self.stack.setCurrentIndex(0)

    def go_to_result(self, payload):
        self.pretriagem_screen.leave_screen()
        self.facial_screen.stop_camera()
        self.arm_test_screen.stop_camera()
        self.joystick_test_screen.leave_screen()
        self.final_result_screen.set_result(build_final_result(payload))
        self.stack.setCurrentWidget(self.final_result_screen)

    def closeEvent(self, event):
        self.pretriagem_screen.leave_screen()
        self.facial_screen.stop_camera()
        self.arm_test_screen.stop_camera()
        self.joystick_test_screen.leave_screen()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
