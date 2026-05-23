import cv2

def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: no se puede abrir la cámara. Prueba con índice 1 usando cv2.VideoCapture(1).")
        return

    print("Presiona 'q' para cerrar la prueba de cámara.")
    while True:
        success, frame = cap.read()
        if not success:
            print("Error: no se recibió imagen de la cámara.")
            break

        cv2.imshow("Prueba de Cámara", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
