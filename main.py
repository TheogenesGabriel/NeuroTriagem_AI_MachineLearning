"""
NeuroTriagem.AI - aplicacao desktop local (estrutura base)
-----------------------------------------------------------
Fluxo de telas: Inicial -> Assimetria Facial -> Teste do Braco (webcam)
-> Teste do Joystick (BitDogLab). A ultima tela e quem aciona o
Random Forest e mostra o veredito final.

Roda um servidor WebSocket local (core/bitdoglab_ws_server.py) em
background - placeholder pra um eventual firmware de sensores
(MAX30102/ADS8232) que ainda nao existe no repositorio da BitDogLab.

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

from core.bitdoglab_ws_server import BitDogLabServer
from screens.arm_test_screen import ArmTestScreen
from screens.facial_screen import FacialAsymmetryScreen
from screens.home_screen import HomeScreen
from screens.joystick_test_screen import JoystickTestScreen

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NeuroTriagem.AI")
        self.resize(1000, 750)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # Servidor WebSocket - placeholder pra um eventual firmware de sensores
        # fisiologicos (ver core/bitdoglab_ws_server.py). O teste de sorriso
        # e o do joystick usam protocolos diferentes (TCP client / serial).
        self.bitdoglab = BitDogLabServer(host="0.0.0.0", port=8765)
        self.bitdoglab.start()

        self.home_screen = HomeScreen(on_start=self.go_to_facial)
        self.facial_screen = FacialAsymmetryScreen(on_next=self.go_to_arm_test, on_back=self.go_to_home)
        self.arm_test_screen = ArmTestScreen(on_next=self.go_to_joystick_test)
        self.joystick_test_screen = JoystickTestScreen(
            on_finish=self.go_to_home,
            bitdoglab=self.bitdoglab,
            facial_screen=self.facial_screen,
            arm_test_screen=self.arm_test_screen,
        )

        self.stack.addWidget(self.home_screen)            # index 0
        self.stack.addWidget(self.facial_screen)           # index 1
        self.stack.addWidget(self.arm_test_screen)         # index 2
        self.stack.addWidget(self.joystick_test_screen)    # index 3
        self.stack.setCurrentIndex(0)

    def go_to_facial(self):
        self.facial_screen.start_camera()
        self.stack.setCurrentIndex(1)

    def go_to_arm_test(self):
        self.facial_screen.stop_camera()
        self.arm_test_screen.start_camera()
        self.stack.setCurrentIndex(2)

    def go_to_joystick_test(self):
        self.arm_test_screen.stop_camera()
        self.joystick_test_screen.enter_screen()
        self.stack.setCurrentIndex(3)

    def go_to_home(self):
        self.facial_screen.stop_camera()
        self.arm_test_screen.stop_camera()
        self.joystick_test_screen.leave_screen()
        self.stack.setCurrentIndex(0)

    def closeEvent(self, event):
        self.bitdoglab.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()