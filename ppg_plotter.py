import sys
import serial
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets
from collections import deque
import numpy as np
import time
import datetime

# --- CONFIGURACIÓN ---
PORT = 'COM15'
BAUD = 115200
WINDOW_SIZE = 500

ACTION_BUTTON_STYLE = """
    QPushButton { 
        background-color: #555555; color: white; border-radius: 5px; 
        padding: 5px; font-weight: bold; border: 1px solid #777777;
        font-size: 20px;
    }
    QPushButton:checked { 
        background-color: #FF6666; color: white; border: 1px solid #FF8888;
    }
    QPushButton:hover { 
        background-color: #666666; 
    }
    QPushButton:checked:hover { 
        background-color: #FF8888; 
    }
"""

class PPGMonitor(QtWidgets.QMainWindow):
    def set_status(self, text, status_type="info"):
        """
        Actualiza la barra de estado con colores y estilos llamativos según el tipo.
        tipos: 'info' (azul), 'success' (verde), 'warning' (naranja), 'error' (rojo)
        """
        colors = {
            "success": ("#00FF88", "rgba(0, 255, 136, 0.15)", "#00FF88"),
            "warning": ("#FFDD44", "rgba(255, 221, 68, 0.15)", "#FFDD44"),
            "error":   ("#FF4444", "rgba(255, 68, 68, 0.15)", "#FF4444"),
            "info":    ("#44AAFF", "rgba(68, 170, 255, 0.15)", "#44AAFF")
        }
        
        fg, bg, border = colors.get(status_type, colors["info"])
        
        self.status_bar.setText(f" ●  {text.upper()}")
        self.status_bar.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {fg};
                font-size: 24px;
                font-weight: 800;
                padding: 20px;
                border: 2px solid {border};
                border-radius: 10px;
                margin: 10px 0px 5px 0px;
            }}
        """)

    def __init__(self):
        super().__init__()
        
        # Configuración Ventana Principal
        self.setWindowTitle("AFE4490 Advanced Monitor (by Medical Open World)")
        self.resize(2700, 1600)
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        
        # Estructuras de Datos
        self.data_lib_id = deque(["?"]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_sample_counter = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_timestamp_us = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_ppg = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_hr  = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_spo2 = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_red = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_ir  = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_amb_ir = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_amb_red = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_ir_sub = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_red_sub = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_red_filt = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.data_ir_filt = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)

        self.is_paused = False
        self.is_plot_paused = False
        self.last_time = None
        self.active_lib = "MOW"  # must match default in main.cpp (start_mow)
        
        self.is_saving = False
        self.save_file = None
        
        self.auto_save_timer = QtCore.QTimer()
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_timer.timeout.connect(self.auto_stop_save)
        
        # Widget Central
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Layout para organizar izquierda (gráficas) y derecha (consola)
        content_layout = QtWidgets.QHBoxLayout()
        
        # 0. Sidebar de Control (Izquierda)
        self.sidebar_layout = QtWidgets.QVBoxLayout()
        self.sidebar_layout.setSpacing(10)
        
        def create_check(label, color, checked=True):
            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(checked)
            cb.setStyleSheet(f"""
                QCheckBox {{ color: {color}; font-weight: bold; font-size: 18px; spacing: 10px; }}
                QCheckBox::indicator {{ 
                    width: 24px; height: 24px; border: 2px solid #555555; 
                    border-radius: 4px; background-color: #1A1A1A; 
                }}
                QCheckBox::indicator:checked {{ 
                    background-color: #666666; 
                    border: 2px solid #BBBBBB;
                    image: url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAdUlEQVR4nO2UQQ7AIAgEWf//5+21aYQFIpfGvRhJnFGJgqRNfGjrwiqCdKzCVB2DRAFC22RnWoAAAAAElFTkSuQmCC");
                }}
            """)
            return cb

        self.label_red = QtWidgets.QLabel("RED")
        self.label_red.setStyleSheet("color: #FF4444; font-weight: 800; font-size: 20px; margin-top: 10px;")
        self.sidebar_layout.addWidget(self.label_red)
        
        self.check_red_raw = create_check("RED (raw)", "#FFFFFF", False)
        self.check_red_amb = create_check("Ambient RED", "#00FFFF", False)
        self.check_red_sub = create_check("RED (clean)", "#FF8888", False)
        self.check_red_filt = create_check("RED (filt)", "#FF0000", True)
        
        self.sidebar_layout.addWidget(self.check_red_raw)
        self.sidebar_layout.addWidget(self.check_red_amb)
        self.sidebar_layout.addWidget(self.check_red_sub)
        self.sidebar_layout.addWidget(self.check_red_filt)
        
        self.label_ir = QtWidgets.QLabel("IR")
        self.label_ir.setStyleSheet("color: #44AAFF; font-weight: 800; font-size: 20px; margin-top: 20px;")
        self.sidebar_layout.addWidget(self.label_ir)
        
        self.check_ir_raw = create_check("IR (raw)", "#FFFFFF", False)
        self.check_ir_amb = create_check("Ambient IR", "#00FFFF", False)
        self.check_ir_sub = create_check("IR (clean)", "#88CCFF", False)
        self.check_ir_filt = create_check("IR (filt)", "#44AAFF", True)
        
        self.sidebar_layout.addWidget(self.check_ir_raw)
        self.sidebar_layout.addWidget(self.check_ir_amb)
        self.sidebar_layout.addWidget(self.check_ir_sub)
        self.sidebar_layout.addWidget(self.check_ir_filt)
        
        # Espaciador para separar checkboxes de botones
        self.sidebar_layout.addSpacing(30)

        # Botones de Acción en el lateral

        self.btn_pause = QtWidgets.QPushButton("PAUSAR\nCAPTURA")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.sidebar_layout.addWidget(self.btn_pause)

        self.btn_pause_plot = QtWidgets.QPushButton("PAUSAR\nGRÁFICAS")
        self.btn_pause_plot.setCheckable(True)
        self.btn_pause_plot.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_pause_plot.clicked.connect(self.toggle_pause_plot)
        self.sidebar_layout.addWidget(self.btn_pause_plot)
        
        self.btn_save = QtWidgets.QPushButton("GUARDAR\nDATOS")
        self.btn_save.setCheckable(True)
        self.btn_save.setStyleSheet(ACTION_BUTTON_STYLE)
        self.btn_save.clicked.connect(self.toggle_save)
        self.sidebar_layout.addWidget(self.btn_save)

        self.sidebar_layout.addSpacing(20)

        label_library = QtWidgets.QLabel("LIBRARY")
        label_library.setStyleSheet("color: #AAAAAA; font-weight: 800; font-size: 20px; margin-top: 10px;")
        self.sidebar_layout.addWidget(label_library)

        self.btn_lib_mow = QtWidgets.QPushButton("MOW")
        self.btn_lib_pc  = QtWidgets.QPushButton("PROTOCENTRAL")
        self.btn_lib_mow.clicked.connect(lambda: self._send_lib_cmd('m'))
        self.btn_lib_pc.clicked.connect(lambda:  self._send_lib_cmd('p'))
        self.sidebar_layout.addWidget(self.btn_lib_mow)
        self.sidebar_layout.addWidget(self.btn_lib_pc)
        self._update_lib_button()

        self.sidebar_layout.addStretch()
        
        left_layout = QtWidgets.QVBoxLayout()
        right_layout = QtWidgets.QVBoxLayout()
        
        # 1. Dashboard de Gráficas (Usando PyQtGraph)
        pg.setConfigOptions(antialias=True)
        self.graphics_layout = pg.GraphicsLayoutWidget()
        left_layout.addWidget(self.graphics_layout, stretch=10)
        
        # Canal Rojo
        self.p1 = self.graphics_layout.addPlot(title="<b style='color:#FF4444'>RED</b>")
        self.curve_red = self.p1.plot(pen=pg.mkPen('#FFFFFF', width=1.5), name="RED (Raw)")
        self.curve_amb_red = self.p1.plot(pen=pg.mkPen('#00FFFF', width=1.5, style=QtCore.Qt.DashLine), name="Ambient RED")
        self.curve_red_sub = self.p1.plot(pen=pg.mkPen('#FF8888', width=1.5), name="RED (Clean)")
        self.curve_red_filt = self.p1.plot(pen=pg.mkPen('#FF0000', width=3), name="RED (Filtered)")
        self.p1.showGrid(x=True, y=True, alpha=0.3)
        
        self.graphics_layout.nextRow()
        
        # Canal IR
        self.p2 = self.graphics_layout.addPlot(title="<b style='color:#44AAFF'>IR</b>")
        self.curve_ir = self.p2.plot(pen=pg.mkPen('#FFFFFF', width=1.5), name="IR (Raw)")
        self.curve_amb_ir = self.p2.plot(pen=pg.mkPen('#00FFFF', width=1.5, style=QtCore.Qt.DashLine), name="Ambient IR")
        self.curve_ir_sub = self.p2.plot(pen=pg.mkPen('#88CCFF', width=1.5), name="IR (Clean)")
        self.curve_ir_filt = self.p2.plot(pen=pg.mkPen('#44AAFF', width=3), name="IR (Filtered)")
        self.p2.showGrid(x=True, y=True, alpha=0.3)
        
        self.graphics_layout.nextRow()
        
        # Fila para HR y SPO2 (en paralelo)
        stats_layout = self.graphics_layout.addLayout()
        self.p_ppg = stats_layout.addPlot(title="<b style='color:#FFFFFF'>Inverted PPG</b>")
        self.curve_ppg = self.p_ppg.plot(pen=pg.mkPen('#FFFFFF', width=2))
        self.p_ppg.showGrid(x=True, y=True, alpha=0.3)

        self.p_spo2 = stats_layout.addPlot(title="<b style='color:#44FF88'>SpO2 (%)</b>")
        self.curve_spo2 = self.p_spo2.plot(pen=pg.mkPen('#44FF88', width=3))
        self.p_spo2.setYRange(80, 100)

        self.p_hr = stats_layout.addPlot(title="<b style='color:#FFDD44'>HEART RATE (BPM)</b>")
        self.curve_hr = self.p_hr.plot(pen=pg.mkPen('#FFDD44', width=3))
        self.p_hr.setYRange(40, 180)

        # Asegurar ancho uniforme
        stats_layout.layout.setColumnStretchFactor(0, 1)
        stats_layout.layout.setColumnStretchFactor(1, 1)
        stats_layout.layout.setColumnStretchFactor(2, 1)

        # 2. Consola de Texto
        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.console.setMinimumWidth(200)
        self.console.setFont(QtGui.QFont("Consolas", 9))
        self.console.setStyleSheet("""
            background-color: #000000; 
            color: #D09000; 
            border: 1px solid #FFAA00;
            padding: 5px;
        """)
        right_layout.addWidget(self.console)

        # 3. Etiqueta de cabecera de campos del puerto serie
        # Timestamp_PC = 15 chars (%H:%M:%S.%f), Df_us = 5 chars (:>5)
        SERIAL_HEADER = (
            f"{'Timestamp_PC':<15},{'Df_us':>5},"
            "LibID,SmpCnt,Ts_us,PPG,SpO2,HR,RED,IR,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt"
        )
        self.header_label = QtWidgets.QLabel(SERIAL_HEADER)
        self.header_label.setFont(QtGui.QFont("Consolas", 9))
        self.header_label.setWordWrap(False)
        self.header_label.setMinimumWidth(0)
        self.header_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored,      # horizontal: ignorar sizeHint → no bloquea splitter
            QtWidgets.QSizePolicy.Preferred     # vertical: normal
        )
        self.header_label.setStyleSheet("""
            QLabel {
                background-color: #1A1000;
                color: #FFAA00;
                padding: 5px 8px;
                border: 1px solid #FFAA00;
                border-top: none;
            }
        """)
        right_layout.addWidget(self.header_label)

        
        # Splitter
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        left_container = QtWidgets.QWidget()
        left_container.setLayout(left_layout)
        right_container = QtWidgets.QWidget()
        right_container.setLayout(right_layout)
        self.splitter.addWidget(left_container)
        self.splitter.addWidget(right_container)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        
        content_layout.addLayout(self.sidebar_layout)
        content_layout.addWidget(self.splitter)
        main_layout.addLayout(content_layout)
        
        # Conectar Checkboxes
        self.check_red_raw.stateChanged.connect(lambda: self.curve_red.setVisible(self.check_red_raw.isChecked()))
        self.check_red_amb.stateChanged.connect(lambda: self.curve_amb_red.setVisible(self.check_red_amb.isChecked()))
        self.check_red_sub.stateChanged.connect(lambda: self.curve_red_sub.setVisible(self.check_red_sub.isChecked()))
        self.check_red_filt.stateChanged.connect(lambda: self.curve_red_filt.setVisible(self.check_red_filt.isChecked()))
        self.check_ir_raw.stateChanged.connect(lambda: self.curve_ir.setVisible(self.check_ir_raw.isChecked()))
        self.check_ir_amb.stateChanged.connect(lambda: self.curve_amb_ir.setVisible(self.check_ir_amb.isChecked()))
        self.check_ir_sub.stateChanged.connect(lambda: self.curve_ir_sub.setVisible(self.check_ir_sub.isChecked()))
        self.check_ir_filt.stateChanged.connect(lambda: self.curve_ir_filt.setVisible(self.check_ir_filt.isChecked()))
        
        # Actualizar visibilidad inicial según checks
        self.curve_red.setVisible(self.check_red_raw.isChecked())
        self.curve_amb_red.setVisible(self.check_red_amb.isChecked())
        self.curve_red_sub.setVisible(self.check_red_sub.isChecked())
        self.curve_red_filt.setVisible(self.check_red_filt.isChecked())
        self.curve_ir.setVisible(self.check_ir_raw.isChecked())
        self.curve_amb_ir.setVisible(self.check_ir_amb.isChecked())
        self.curve_ir_sub.setVisible(self.check_ir_sub.isChecked())
        self.curve_ir_filt.setVisible(self.check_ir_filt.isChecked())

        # Etiqueta de estado
        self.status_bar = QtWidgets.QLabel()
        self.status_bar.setAlignment(QtCore.Qt.AlignCenter)
        main_layout.addWidget(self.status_bar)
        self.set_status(f"Conectando a {PORT}...", "info")
        
        # Conexión Serial
        try:
            self.ser = serial.Serial(PORT, BAUD, timeout=0.1)
            self.set_status(f"Sistema ONLINE - Conectado a {PORT} @ {BAUD}", "success")
            self.console.appendPlainText("Timestamp_PC   ,Df_us,$LibID,SmpCnt,Ts_us,PPG,SpO2,HR,RED,IR,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt")
        except Exception as e:
            self.set_status(f"ERROR: No se pudo abrir {PORT}", "error")
            QtWidgets.QMessageBox.critical(self, "Error de Puerto", f"No se pudo abrir {PORT}:\n{str(e)}")
            sys.exit(1)
            
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_data)
        self.timer.start(20)
        
    STYLE_LIB_ACTIVE = """
        QPushButton {{
            background-color: {bg}; color: {fg};
            border-radius: 5px; padding: 5px; font-weight: bold;
            border: 2px solid {fg}; font-size: 18px;
        }}
        QPushButton:hover {{ background-color: {bgh}; }}
    """
    STYLE_LIB_INACTIVE = """
        QPushButton {
            background-color: #222222; color: #555555;
            border-radius: 5px; padding: 5px; font-weight: bold;
            border: 2px solid #444444; font-size: 18px;
        }
        QPushButton:hover { background-color: #2A2A2A; }
    """

    def _update_lib_button(self):
        mow_active = (self.active_lib == "MOW")
        self.btn_lib_mow.setStyleSheet(
            self.STYLE_LIB_ACTIVE.format(bg="#3A2A00", fg="#FFAA00", bgh="#4A3800")
            if mow_active else self.STYLE_LIB_INACTIVE)
        self.btn_lib_pc.setStyleSheet(
            self.STYLE_LIB_ACTIVE.format(bg="#3A2A00", fg="#FFAA00", bgh="#4A3800")
            if not mow_active else self.STYLE_LIB_INACTIVE)

    def _send_lib_cmd(self, cmd):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            return
        self.ser.write(cmd.encode())

    def toggle_pause(self):
        self.is_paused = self.btn_pause.isChecked()
        if self.is_paused:
            self.btn_pause.setText("REANUDAR\nCAPTURA")
            self.set_status("Captura PAUSADA", "warning")
        else:
            self.btn_pause.setText("PAUSAR\nCAPTURA")
            self.set_status(f"Sistema ONLINE - Conectado a {PORT} @ {BAUD}", "success")

    def toggle_pause_plot(self):
        self.is_plot_paused = self.btn_pause_plot.isChecked()
        if self.is_plot_paused:
            self.btn_pause_plot.setText("REANUDAR\nGRÁFICAS")
        else:
            self.btn_pause_plot.setText("PAUSAR\nGRÁFICAS")

    def auto_stop_save(self):
        if self.is_saving:
            self.btn_save.setChecked(False)
            self.toggle_save()
            self.set_status("Stream finalizado (Auto-Stop 1000s)", "info")

    def toggle_save(self):
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.is_paused:
            self.btn_save.setChecked(False)
            filename = f"ppg_data_snap_{now_str}.csv"
            try:
                with open(filename, "w") as f:
                    f.write("LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,PPG,HR,SpO2,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt\n")
                    for i in range(len(self.data_sample_counter)):
                        f.write(f"{self.data_lib_id[i]},{self.data_sample_counter[i]},{self.data_timestamp_us[i]},{self.data_ppg[i]},{self.data_hr[i]},{self.data_spo2[i]},{self.data_red[i]},{self.data_ir[i]},{self.data_amb_red[i]},{self.data_amb_ir[i]},{self.data_red_sub[i]},{self.data_ir_sub[i]},{self.data_red_filt[i]},{self.data_ir_filt[i]}\n")
                self.set_status(f"Memoria guardada en {filename}", "success")
            except Exception as e:
                self.set_status(f"Error al guardar memoria: {e}", "error")
        else:
            self.is_saving = self.btn_save.isChecked()
            if self.is_saving:
                self.btn_save.setText("DETENER\nGRABACIÓN")
                filename = f"ppg_data_stream_{now_str}.csv"
                try:
                    self.save_file = open(filename, "w")
                    self.save_file.write("Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,PPG,HR,SpO2,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt\n")
                    self.set_status(f"GRABANDO EN TIEMPO REAL: {filename}", "warning")
                    self.auto_save_timer.start(1000 * 1000)
                except Exception as e:
                    self.set_status(f"Error al grabar: {e}", "error")
                    self.is_saving = False
                    self.btn_save.setChecked(False)
            else:
                self.auto_save_timer.stop()
                self.btn_save.setText("GUARDAR\nDATOS")
                if self.save_file:
                    self.save_file.close()
                    self.save_file = None
                self.set_status(f"Sistema ONLINE - Conectado a {PORT} @ {BAUD}", "success")

    def update_data(self):
        if self.is_paused:
            # Keep draining the serial buffer so the ESP32 doesn't block
            if hasattr(self, 'ser') and self.ser.is_open and self.ser.in_waiting > 0:
                self.ser.read(self.ser.in_waiting)
            return
        try:
            if hasattr(self, 'ser') and self.ser.is_open and self.ser.in_waiting > 0:
                while self.ser.is_open and self.ser.in_waiting > 0:
                    line_raw = self.ser.readline()
                    try:
                        line = line_raw.decode('utf-8', errors='ignore').strip()
                    except: continue
                    if not line: continue

                    # Confirmation messages from ESP32 (e.g. "# Switched to mow_afe4490")
                    if line.startswith('#'):
                        self.console.appendPlainText(line)
                        if 'mow' in line.lower():
                            self.active_lib = "MOW"
                            self._update_lib_button()
                            self.set_status("Librería activa: mow_afe4490", "info")
                        elif 'protocentral' in line.lower():
                            self.active_lib = "PROTOCENTRAL"
                            self._update_lib_button()
                            self.set_status("Librería activa: protocentral", "info")
                        continue

                    current_time_perf = time.perf_counter()
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")
                    diff_us = int((current_time_perf - self.last_time) * 1e6) if self.last_time is not None else 0
                    self.last_time = current_time_perf
                    
                    csv_line = f"{timestamp},{diff_us:>5},{line}"
                    self.console.appendPlainText(csv_line)
                    if getattr(self, 'is_saving', False) and getattr(self, 'save_file', None):
                        self.save_file.write(csv_line + "\n")
                        self.save_file.flush()
                    if self.console.blockCount() > 500:
                        cursor = self.console.textCursor()
                        cursor.movePosition(QtGui.QTextCursor.Start)
                        cursor.select(QtGui.QTextCursor.BlockUnderCursor)
                        cursor.removeSelectedText()
                        cursor.deleteChar()
                    self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())
                    self.console.horizontalScrollBar().setValue(0)
                    
                    if not line.startswith('$'):
                        continue
                    parts = line[1:].split(',')  # strip leading '$'
                    if len(parts) >= 14:
                        try:
                            # 0:LibID, 1:SmpCnt, 2:Ts_us, 3:PPG, 4:SpO2, 5:HR, 6:RED, 7:IR, 8:AmbRED, 9:AmbIR, 10:REDSub, 11:IRSub, 12:REDFilt, 13:IRFilt
                            self.data_lib_id.append(parts[0])
                            p = [float(x) for x in parts[1:14]]
                            self.data_sample_counter.append(int(p[0]))
                            self.data_timestamp_us.append(p[1])
                            self.data_ppg.append(p[2])
                            self.data_spo2.append(p[3])
                            self.data_hr.append(p[4])
                            self.data_red.append(p[5])
                            self.data_ir.append(p[6])
                            self.data_amb_red.append(p[7])
                            self.data_amb_ir.append(p[8])
                            self.data_red_sub.append(p[9])
                            self.data_ir_sub.append(p[10])
                            self.data_red_filt.append(p[11])
                            self.data_ir_filt.append(p[12])
                        except ValueError: pass
                
                if not self.is_plot_paused:
                    self.p_spo2.setTitle(f"<b style='color:#44FF88'>SpO2: {self.data_spo2[-1]:.1f} %</b>")
                    self.p_hr.setTitle(f"<b style='color:#FFDD44'>HR: {int(self.data_hr[-1])} bpm</b>")
                    self.curve_ppg.setData(list(self.data_ppg))
                    self.curve_spo2.setData(list(self.data_spo2))
                    self.curve_hr.setData(list(self.data_hr))
                    self.curve_red.setData(list(self.data_red))
                    self.curve_ir.setData(list(self.data_ir))
                    self.curve_amb_red.setData(list(self.data_amb_red))
                    self.curve_amb_ir.setData(list(self.data_amb_ir))
                    self.curve_red_sub.setData(list(self.data_red_sub))
                    self.curve_ir_sub.setData(list(self.data_ir_sub))
                    self.curve_red_filt.setData(list(self.data_red_filt))
                    self.curve_ir_filt.setData(list(self.data_ir_filt))
                    
        except Exception as e:
            print(f"Error en loop: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        # setSizes debe llamarse tras show() para que Qt no lo sobreescriba
        QtCore.QTimer.singleShot(0, lambda: self.splitter.setSizes([1800, 900]))

    def closeEvent(self, event):
        if getattr(self, 'is_saving', False) and getattr(self, 'save_file', None):
            self.save_file.close()
        if hasattr(self, 'ser') and self.ser.is_open:
            self.ser.close()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    window = PPGMonitor()
    window.show()
    sys.exit(app.exec_())
