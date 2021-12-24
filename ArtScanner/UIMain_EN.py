import ctypes
import json
import os
import sys
import time

import mouse
import win32api
import win32gui
from PyQt5.QtCore import (pyqtSignal, pyqtSlot, QObject, QThread,
                          QMutex, QWaitCondition, Qt)
from PyQt5.QtGui import (QMovie, QPixmap)
from PyQt5.QtWidgets import (QMainWindow, QApplication, QDialog,
                             QWidget, QCheckBox, QHBoxLayout)

import ocr_EN
import utils
import ArtsInfo
from art_saver_EN import ArtDatabase
from art_scanner_logic import ArtScannerLogic, GameInfo
from rcc import About_Dialog_EN
from rcc import Help_Dialog_EN
from rcc import ExtraSettings_Dialog_EN
from rcc import InputWindow_Dialog_EN
from rcc.MainWindow_EN import Ui_MainWindow


class AboutDlg(QDialog, About_Dialog_EN.Ui_Dialog):
    def __init__(self, parent=None):
        super(AboutDlg, self).__init__(parent)
        self.setupUi(self)


class HelpDlg(QDialog, Help_Dialog_EN.Ui_Dialog):
    def __init__(self, parent=None):
        super(HelpDlg, self).__init__(parent)
        self.setupUi(self)


class InputWindowDlg(QDialog, InputWindow_Dialog_EN.Ui_Dialog):
    retVal = pyqtSignal(str)

    def __init__(self, parent=None):
        super(InputWindowDlg, self).__init__(parent)
        self.setupUi(self)
        self.pushButton.clicked.connect(self.handleClick)

    @pyqtSlot()
    def handleClick(self):
        self.retVal.emit(self.lineEdit.text())


class ExtraSettingsDlg(QDialog, ExtraSettings_Dialog_EN.Ui_Dialog):
    acceptSignal = pyqtSignal(dict)

    def _addCheckboxAt(self, row: int, col: int, state: bool, text: str = ""):
        checkBoxWidget = QWidget()
        checkBox = QCheckBox(text)
        layoutCheckbox = QHBoxLayout(checkBoxWidget)
        layoutCheckbox.addWidget(checkBox)
        layoutCheckbox.setAlignment(Qt.AlignLeft)
        layoutCheckbox.setContentsMargins(10, 0, 0, 0)

        if state:
            checkBox.setChecked(True)
        else:
            checkBox.setChecked(False)

        self._checkboxes.append(checkBox)
        self.tableWidget.setCellWidget(row, col, checkBoxWidget)

    def __init__(self, settings, parent=None):
        super(ExtraSettingsDlg, self).__init__(parent)
        self.setupUi(self)

        self._checkboxes = []

        self.checkBox.setChecked(settings['EnhancedCaptureWindow'])
        self.checkBox_2.setChecked(settings['ExportAllFormats'])
        self.checkBox_3.setChecked(settings['FilterArtsByName'])
        self.checkBox_4.setEnabled(settings['FilterArtsByName'])
        self.checkBox_5.setChecked(settings['ExportAllImages'])
        self.tableWidget.setEnabled(settings['FilterArtsByName'])
        self.tabWidget.setCurrentIndex(settings["TabIndex"])

        self.checkBox_3.clicked.connect(self.handleAdvancedSettingsClicked)
        self.checkBox_4.clicked.connect(self.handleSelectAllClicked)
        self.pushButton.clicked.connect(self.handleAccept)

        self.tableWidget.setColumnCount(1)
        self.tableWidget.setRowCount(len(ArtsInfo.Setnames_EN))
        self.tableWidget.horizontalHeader().setStretchLastSection(True)

        for i, e in enumerate(ArtsInfo.Setnames_EN):
            self._addCheckboxAt(i, 0, settings['Filter'][i], e)

    @pyqtSlot()
    def handleSelectAllClicked(self):
        if self.checkBox_4.isChecked():
            for e in self._checkboxes:
                e.setChecked(True)
        else:
            for e in self._checkboxes:
                e.setChecked(False)

    @pyqtSlot()
    def handleAdvancedSettingsClicked(self):
        if self.checkBox_3.isChecked():
            self.tableWidget.setEnabled(True)
            self.checkBox_4.setEnabled(True)
        else:
            self.tableWidget.setEnabled(False)
            self.checkBox_4.setEnabled(False)

    @pyqtSlot()
    def handleAccept(self):
        settings = {
            "EnhancedCaptureWindow": self.checkBox.isChecked(),
            "ExportAllFormats": self.checkBox_2.isChecked(),
            "ExportAllImages": self.checkBox_5.isChecked(),
            "FilterArtsByName": self.checkBox_3.isChecked(),
            "Filter": [i.isChecked() for i in self._checkboxes],
            "TabIndex": self.tabWidget.currentIndex()
        }
        self.acceptSignal.emit(settings)


class UIMain(QMainWindow, Ui_MainWindow):
    startScanSignal = pyqtSignal(dict)
    initializeSignal = pyqtSignal()
    detectGameInfoSignal = pyqtSignal(bool)
    setWindowNameSignal = pyqtSignal(str)

    def __init__(self):
        super(UIMain, self).__init__()
        self.setupUi(self)

        self.exportFileName = ''
        self.gif = QMovie(':/rcc/rcc/loading.gif')
        self.picOk = QPixmap(':/rcc/rcc/ok.png')

        self._settings = {
            "EnhancedCaptureWindow": False,
            "ExportAllFormats": False,
            "ExportAllImages": False,
            "FilterArtsByName": False,
            "Filter": [True for _ in ArtsInfo.Setnames_EN],
            "TabIndex": 0
        }
        self._helpDlg = HelpDlg(self)
        self._isHelpDlgShowing = False

        self.logger = utils.logger

        # 连接按钮
        self.pushButton.clicked.connect(self.startScan)
        self.pushButton_2.clicked.connect(self.captureWindow)
        self.pushButton_3.clicked.connect(self.showHelpDlg)
        self.pushButton_4.clicked.connect(self.showExportedFile)
        self.pushButton_5.clicked.connect(self.showExtraSettings)
        self.pushButton_6.clicked.connect(self.showAboutDlg)

        self.radioButton.clicked.connect(self.selectedMona)
        self.radioButton_2.clicked.connect(self.selectedGenmo)
        self.radioButton_3.clicked.connect(self.selectedGOOD)

        # 创建工作线程
        self.worker = Worker()
        self.workerThread = QThread()
        self.worker.moveToThread(self.workerThread)

        self.worker.printLog.connect(self.printLog)
        self.worker.printErr.connect(self.printErr)
        self.worker.working.connect(self.onWorking)
        self.worker.endWorking.connect(self.endWorking)
        self.worker.endInit.connect(self.endInit)
        self.worker.endScan.connect(self.endScan)
        self.worker.showInputWindow.connect(self.showInputWindowName)

        self.initializeSignal.connect(self.worker.initEngine)
        self.detectGameInfoSignal.connect(self.worker.detectGameInfo)
        self.startScanSignal.connect(self.worker.scanArts)
        self.setWindowNameSignal.connect(self.worker.setWindowName)

        self.workerThread.start()

        self.initialize()

    # 通知工作线程进行初始化
    def initialize(self):
        self.logger.info("Worker thread initializing.")
        self.pushButton.setEnabled(False)
        self.pushButton_2.setEnabled(False)
        self.initializeSignal.emit()

    @pyqtSlot()
    def endInit(self):
        self.pushButton.setEnabled(True)
        self.pushButton_2.setEnabled(True)

    @pyqtSlot()
    def onWorking(self):
        self.label.setMovie(self.gif)
        self.gif.start()

    @pyqtSlot()
    def endWorking(self):
        self.label.setPixmap(self.picOk)

    @pyqtSlot()
    def showHelpDlg(self):
        self._helpDlg.accept()
        self.logger.info("Help dialog shown.")
        point = self.rect().topRight()
        globalPoint = self.mapToGlobal(point)
        self._helpDlg.move(globalPoint)
        self._helpDlg.show()

    @pyqtSlot()
    def showAboutDlg(self):
        self.logger.info("About dialog shown.")
        dlg = AboutDlg(self)
        dlg.exec()

    @pyqtSlot()
    def selectedMona(self):
        self.logger.info("Mona selected.")
        self.checkBox.setChecked(True)
        self.checkBox_2.setChecked(True)
        self.checkBox_3.setChecked(False)
        self.checkBox_4.setChecked(False)
        self.checkBox_5.setChecked(False)

        self.spinBox.setValue(0)
        self.spinBox_2.setValue(20)

    @pyqtSlot()
    def selectedGenmo(self):
        self.logger.info("Genmo Calc selected.")
        self.checkBox.setChecked(True)
        self.checkBox_2.setChecked(False)
        self.checkBox_3.setChecked(False)
        self.checkBox_4.setChecked(False)
        self.checkBox_5.setChecked(False)

        self.spinBox.setValue(4)
        self.spinBox_2.setValue(20)

    @pyqtSlot()
    def selectedGOOD(self):
        self.logger.info("GOOD selected.")
        self.checkBox.setChecked(True)
        self.checkBox_2.setChecked(True)
        self.checkBox_3.setChecked(False)
        self.checkBox_4.setChecked(False)
        self.checkBox_5.setChecked(False)

        self.spinBox.setValue(0)
        self.spinBox_2.setValue(20)

    @pyqtSlot()
    def showExtraSettings(self):
        self.logger.info("Extra settings dialog shown.")
        dlg = ExtraSettingsDlg(self._settings, self)
        dlg.acceptSignal.connect(self.handleExtraSettings)
        dlg.exec()

    @pyqtSlot(str, bool)
    def showInputWindowName(self, window_name: str, isDup: bool):
        self.logger.info(f"Input window name dialog shown. window_name={window_name} isDup={isDup}")
        dlg = InputWindowDlg(self)
        if not isDup:
            dlg.label.setText(f"未找到标题为 {window_name} 的窗口，请输入窗口标题后重新捕获")
        else:
            dlg.label.setText(f"找到多个标题为 {window_name} 的窗口，请输入窗口标题后重新捕获")
        dlg.retVal.connect(self.handleInputWindowRet)
        dlg.exec()

    @pyqtSlot(str)
    def handleInputWindowRet(self, window_name):
        self.logger.info(f"Window name returned. window_name={window_name}")
        self.setWindowNameSignal.emit(window_name)

    @pyqtSlot(str)
    def printLog(self, log: str):
        self.logger.info(f"Info message shown. msg={log}")
        self.textBrowser_3.append(log)
        QApplication.processEvents()

    @pyqtSlot(str)
    def printErr(self, err: str):
        self.logger.error(f"Error message shown. msg={err}")
        self.textBrowser_3.append(f'<font color="red">{err}</font>')

    @pyqtSlot()
    def captureWindow(self):
        self.detectGameInfoSignal.emit(self._settings['EnhancedCaptureWindow'])

    @pyqtSlot()
    def startScan(self):
        info = {
            "star": [self.checkBox_5.isChecked(),
                     self.checkBox_4.isChecked(),
                     self.checkBox_3.isChecked(),
                     self.checkBox_2.isChecked(),
                     self.checkBox.isChecked()],
            "levelMin": self.spinBox.value(),
            "levelMax": self.spinBox_2.value(),
            "delay": self.doubleSpinBox.value(),
            "exporter": (0 if self.radioButton.isChecked() else
                         1 if self.radioButton_2.isChecked() else
                         2 if self.radioButton_3.isChecked() else -1),
            "ExtraSettings": self._settings
        }
        self.logger.info(f"Start scan with settings. {info}")

        self.setUIEnabled(False)

        self.startScanSignal.emit(info)

    def setUIEnabled(self, e: bool):
        self.pushButton.setEnabled(e)
        self.checkBox.setEnabled(e)
        self.checkBox_2.setEnabled(e)
        self.checkBox_3.setEnabled(e)
        self.checkBox_4.setEnabled(e)
        self.checkBox_5.setEnabled(e)

        self.spinBox.setEnabled(e)
        self.spinBox_2.setEnabled(e)
        self.doubleSpinBox.setEnabled(e)

        self.radioButton.setEnabled(e)
        self.radioButton_2.setEnabled(e)
        self.radioButton_3.setEnabled(e)

    @pyqtSlot(str)
    def endScan(self, filename: str):
        self.setUIEnabled(True)
        self.exportFileName = filename

    @pyqtSlot()
    def showExportedFile(self):
        if self.exportFileName != '':
            s = "/select, " + os.path.abspath(self.exportFileName)
            win32api.ShellExecute(None, "open", "explorer.exe", s, None, 1)
        else:
            self.printErr("No exported file")

    @pyqtSlot(dict)
    def handleExtraSettings(self, ret: dict):
        self.logger.info(f"Extra settings returned. ret={ret}")
        self._settings = ret
        self.groupBox_4.setEnabled(not self._settings['ExportAllFormats'])


class Worker(QObject):
    printLog = pyqtSignal(str)
    printErr = pyqtSignal(str)
    working = pyqtSignal()
    endWorking = pyqtSignal()
    endInit = pyqtSignal()
    endScan = pyqtSignal(str)
    showInputWindow = pyqtSignal(str, bool)

    def __init__(self):
        super(Worker, self).__init__()
        self.isQuit = False
        self.workingMutex = QMutex()
        self.cond = QWaitCondition()
        self.isInitialized = False
        self.isWindowCaptured = False

        self.logger = utils.logger

        self.windowName = 'Genshin Impact'
        # in initEngine
        self.game_info = None
        self.model = None
        self.bundle_dir = None

        # init in scanArts
        self.art_id = 0
        self.saved = 0
        self.skipped = 0
        self.failed = 0
        self.star_dist = [0, 0, 0, 0, 0]
        self.star_dist_saved = [0, 0, 0, 0, 0]
        self.detectSettings = None

    @pyqtSlot()
    def initEngine(self):
        self.working.emit()

        # yield the thread
        time.sleep(0.1)
        self.log('initializing, please wait...')

        # 创建文件夹
        os.makedirs('artifacts', exist_ok=True)
        self.log('Checking DPI settings...')
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                self.error('It is detected that the process DPI setting is not supported.'
                           '(maybe the system version is lower than Win10)')
                self.error('The program will continue...')
            except:
                self.error('It is detected that reading the system DPI setting is not supported.'
                           '(maybe the system version is lower than Win8) ')
                self.error('The program will continue...')

        self.endWorking.emit()

        self.detectGameInfo(False)

        self.working.emit()
        self.log('Initializing the OCR model...')
        if len(sys.argv) > 1:
            self.bundle_dir = sys.argv[1]
        else:
            self.bundle_dir = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
        self.model = ocr_EN.OCR(model_weight=os.path.join(self.bundle_dir, 'weights_EN.hdf5'))

        self.log('Initialize is finished.')
        if self.isWindowCaptured:
            self.log('The window has been captured, '
                     'please check that the number of rows and columns is correct before start scanning.')
            self.log(f'rows: {self.game_info.art_rows} , columns: {self.game_info.art_cols}')
            self.log("If that's wrong, please change the resolution and try again")
        else:
            self.error('The window is not captured, please recapture the window before start scanning.')

        self.log('Please open Bag - Artifacts and turn the page to the top before start scanning.')
        self.endWorking.emit()
        self.endInit.emit()

    # 捕获窗口与计算边界
    @pyqtSlot(bool)
    def detectGameInfo(self, isEnhanced: bool):
        self.working.emit()
        if not isEnhanced:
            self.log('Trying to capture the window...')
            hwnd = self.captureWindow()
        else:
            self.log(f'Capture window {self.windowName} in enhanced mode...')
            hwnd = self.captureWindowEnhanced()
        if self.isWindowCaptured:
            self.game_info = GameInfo(hwnd)
            if self.game_info.w == 0 or self.game_info.h == 0:
                self.isWindowCaptured = False
                self.error("The current Genshin Impact window is in full-screen mode or minimized, "
                           "please adjust and recapture the window.")
            else:
                self.game_info.calculateCoordinates()
        self.endWorking.emit()

    # 捕获窗口
    def captureWindow(self) -> int:
        hwnd = win32gui.FindWindow("UnityWndClass", "Genshin Impact")
        if hwnd > 0:
            self.isWindowCaptured = True
            self.log('Capture window succeeded.')
        else:
            self.isWindowCaptured = False
            self.error('Capture window failed.')
        return hwnd

    @pyqtSlot(str)
    def setWindowName(self, name: str):
        self.windowName = name
        self.log(f'Settle to {name}, pls capture again')

    # 捕获窗口 强化版
    @pyqtSlot(str)
    def captureWindowEnhanced(self) -> int:
        hwnd = -1
        windows = utils.findWindowsByName(self.windowName)
        if len(windows) == 0:
            self.isWindowCaptured = False
            self.showInputWindow.emit(self.windowName, False)
        elif len(windows) == 1:
            self.isWindowCaptured = True
            hwnd = windows[0][0]
            self.log(f"Capture window successful with title {self.windowName}")
        else:
            self.isWindowCaptured = False
            self.showInputWindow.emit(self.windowName, True)
        return hwnd

    @pyqtSlot(dict)
    def scanArts(self, info: dict):
        self.working.emit()
        if not self.isWindowCaptured:
            self.error('The window is not captured, please recapture the window.')
            self.endScan.emit('')
            self.endWorking.emit()
            return

        self.model.setScaleRatio(self.game_info.scale_ratio)

        if info['levelMin'] > info['levelMax']:
            self.error('The min and max settings are incorrect.')
            self.endScan.emit('')
            self.endWorking.emit()
            return
        self.detectSettings = info
        artifactDB = ArtDatabase()
        artScanner = ArtScannerLogic(self.game_info)

        exporter = [artifactDB.exportGenshinArtJSON,
                    artifactDB.exportGenmoCalcJSON,
                    artifactDB.exportGOODJSON]
        export_name = ['artifacts.genshinart.json',
                       'artifacts.genmocalc.json',
                       'artifacts.GOOD.json']

        mouse.on_middle_click(artScanner.interrupt)

        self.log('Scanning will start in 3 seconds...')
        time.sleep(1)
        utils.setWindowToForeground(self.game_info.hwnd)

        self.log('3...')
        time.sleep(1)
        self.log('2...')
        time.sleep(1)
        self.log('1...')
        time.sleep(1)

        self.log('Aligning...')
        artScanner.alignFirstRow()
        self.log('Complete, scan will start now.')
        time.sleep(0.5)

        start_row = 0
        self.art_id = 0
        self.saved = 0
        self.skipped = 0
        self.failed = 0
        self.star_dist = [0, 0, 0, 0, 0]
        self.star_dist_saved = [0, 0, 0, 0, 0]

        def autoCorrect(detected_info):
            detected_info['name'] = utils.name_auto_correct_EN(detected_info['name'])
            detected_info['setid'] = [i for i, v in enumerate(
                ArtsInfo.ArtNames_EN) if detected_info['name'] in v][0]
            detected_info['main_attr_name'] = utils.attr_auto_correct_EN(detected_info['main_attr_name'])
            for tag in sorted(detected_info.keys()):
                if "subattr_" in tag:
                    info = detected_info[tag].split('+')
                    detected_info[tag] = utils.attr_auto_correct_EN(info[0]) + "+" + info[1]

        def artFilter(detected_info, art_img):
            autoCorrect(detected_info)

            self.star_dist[detected_info['star'] - 1] += 1
            detectedLevel = utils.decodeValue(detected_info['level'])
            detectedStar = utils.decodeValue(detected_info['star'])

            if (self.detectSettings["ExtraSettings"]["FilterArtsByName"] and
                    (not self.detectSettings["ExtraSettings"]["Filter"][detected_info['setid']])):
                self.logger.info(f"[FilterArtsByName] Skipped a Artifact."
                                 f" id: {self.art_id + 1} detected info: {detected_info} set: {ArtsInfo.Setnames_EN[detected_info['setid']]}")
                self.skipped += 1
                status = 1
            elif not ((self.detectSettings['levelMin'] <= detectedLevel <= self.detectSettings['levelMax']) and
                      (self.detectSettings['star'][detectedStar - 1])):
                self.logger.info(f"[FilterArtsByLevelAndStar] Skipped a Artifact."
                                 f" id: {self.art_id + 1} detected info: {detected_info}")
                self.skipped += 1
                status = 1
            elif artifactDB.add(detected_info, art_img):
                self.logger.info(f"[ArtifactDB] Saved a Artifact."
                                 f" id: {self.art_id + 1} detected info: {detected_info}")
                self.saved += 1
                status = 2
                self.star_dist_saved[detected_info['star'] - 1] += 1
            else:
                self.logger.info(f"[ArtifactDB] Failed to save a Artifact."
                                 f" id: {self.art_id + 1} detected info: {detected_info}")
                status = 3
                self.failed += 1
            self.art_id += 1
            saveImg(detected_info, art_img, status)

        def saveImg(detected_info, art_img, status):
            if self.detectSettings['ExtraSettings']['ExportAllImages']:
                if status == 3:
                    art_img.save(f'artifacts/fail_{self.art_id}.png')
                    s = json.dumps(detected_info, ensure_ascii=False)
                    with open(f"artifacts/fail_{self.art_id}.json", "wb") as f:
                        f.write(s.encode('utf-8'))
                else:
                    art_img.save(f'artifacts/{self.art_id}.png')
                    s = json.dumps(detected_info, ensure_ascii=False)
                    with open(f"artifacts/{self.art_id}.json", "wb") as f:
                        f.write(s.encode('utf-8'))
            else:
                # export only failed
                if status == 3:
                    art_img.save(f'artifacts/fail_{self.art_id}.png')
                    s = json.dumps(detected_info, ensure_ascii=False)
                    with open(f"artifacts/fail_{self.art_id}.json", "wb") as f:
                        f.write(s.encode('utf-8'))

        def artscannerCallback(art_img):
            detectedInfo = self.model.detect_info(art_img)
            artFilter(detectedInfo, art_img)
            self.log(f"Detected: {self.art_id}, Saved: {self.saved}, Skipped: {self.skipped}")

        try:
            while True:
                if artScanner.stopped or not artScanner.scanRows(rows=range(start_row, self.game_info.art_rows),
                                                                 callback=artscannerCallback) or start_row != 0:
                    break
                start_row = self.game_info.art_rows - artScanner.scrollToRow(self.game_info.art_rows, max_scrolls=20,
                                                                             extra_scroll=int(
                                                                                 self.game_info.art_rows > 5),
                                                                             interval=self.detectSettings['delay'])
                if start_row == self.game_info.art_rows:
                    break
            if artScanner.stopped:
                self.log('Interrupted')
            else:
                self.log('Completed')
        except Exception as e:
            self.logger.exception(e)
            self.error(repr(e))
            self.log('Stopped with an Error.')

        if self.saved != 0:
            if info['ExtraSettings']['ExportAllFormats']:
                list(map(lambda exp, name: exp(name), exporter, export_name))
            else:
                self.log(f"File exported as: {export_name[info['exporter']]}")
                exporter[info['exporter']](export_name[info['exporter']])
        self.log(f'Scanned: {self.art_id}')
        self.log(f'  - Saved:   {self.saved}')
        self.log(f'  - Skipped: {self.skipped}')
        self.log(f'Failed: {self.failed}')
        self.log('The failed result has been stored in the folder artifacts_EN.')

        self.log('Star: (Saved / Scanned)')
        self.log(f'5: {self.star_dist_saved[4]} / {self.star_dist[4]}')
        self.log(f'4: {self.star_dist_saved[3]} / {self.star_dist[3]}')
        self.log(f'3: {self.star_dist_saved[2]} / {self.star_dist[2]}')
        self.log(f'2: {self.star_dist_saved[1]} / {self.star_dist[1]}')
        self.log(f'1: {self.star_dist_saved[0]} / {self.star_dist[0]}')

        del artifactDB
        self.endScan.emit(export_name[info['exporter']])
        self.endWorking.emit()

    def log(self, content: str):
        self.printLog.emit(content)

    def error(self, err: str):
        self.printErr.emit(err)


if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)
        uiMain = UIMain()
        uiMain.show()
        app.exec()
    except Exception as excp:
        utils.logger.exception(excp)
        win32api.ShellExecute(0, 'open', 'cmd.exe',
                              r'/c echo Unhandled exception occured. Please contact with the author. && pause', None, 1)
