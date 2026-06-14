import sys
from PyQt6.QtWidgets import QApplication
from ebook_manager.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("电子书元数据管理器")
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
