

import socket
import time

import cv2
from ultralytics import YOLO

# --- Configuracao ---------------------------------------------------------
MODEL_PATH = "runs/detect/train/weights/best.pt"

SMILE_CLASS_NAME = "smile"                  # ajuste para o nome exato da class                                          # que voce usou ao rotular no Roboflow
CONFIDENCE_THRESHOLD = 0.6

PICO_IP = "10.231.10.202"                    # printed by the firmware over USB serial
PICO_PORT = 4242

COOLDOWN_SECONDS = 6                        # avoid re-triggering every frame
CAMERA_INDEX = 0


def notify_pico() -> None:
    """Opens a short-lived TCP connection to the Pico and sends the trigger."""
    try:
        with socket.create_connection((PICO_IP, PICO_PORT), timeout=3) as sock:
            sock.sendall(b"SMILE\n")
            ack = sock.recv(32)
            print(f"[pico] {ack.decode(errors='ignore').strip()}")
    except OSError as exc:
        print(f"[pico] could not reach {PICO_IP}:{PICO_PORT} -> {exc}")


def main() -> None:
    model = YOLO(MODEL_PATH)

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        raise RuntimeError("Nao foi possivel abrir a webcam.")

    last_trigger = 0.0
    print("Detector de sorriso (YOLOv8 local) rodando. Pressione 'q' para sair.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue

            results = model.predict(frame, conf=CONFIDENCE_THRESHOLD, verbose=False)
            annotated = results[0].plot()  # desenha as caixas na imagem
            cv2.imshow("Smile Detector", annotated)

            now = time.time()
            if now - last_trigger > COOLDOWN_SECONDS:
                names = results[0].names
                classes_detected = [names[int(c)] for c in results[0].boxes.cls]
                if SMILE_CLASS_NAME in classes_detected:
                    print("Sorriso detectado! Avisando a BitDogLab...")
                    notify_pico()
                    last_trigger = now

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()