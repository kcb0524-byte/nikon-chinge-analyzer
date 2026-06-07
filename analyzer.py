#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
니콘 친게 음원 감별사
PyQt6 기반 — macOS NSApp 드래그앤드롭 지원
"""

import sys
import os
import math
import threading
import numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QFileDialog,
    QFrame, QSplitter, QScrollArea, QSizePolicy, QProgressBar,
    QAbstractItemView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl, QMimeData
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QLinearGradient, QBrush, QPalette,
    QDragEnterEvent, QDropEvent
)

# ─────────────────────────────────────────────
# 색상
# ─────────────────────────────────────────────
BG      = '#07070f'
PANEL   = '#0f0f1e'
CARD    = '#13132a'
ACCENT  = '#6688ff'
TXT     = '#e8e8ff'
TXT_SUB = '#7777aa'
GREEN   = '#00e676'
ORANGE  = '#ffab40'
RED     = '#ff4444'

AUDIO_EXTS = {'.flac','.wav','.aiff','.aif','.ogg','.mp3','.m4a','.aac','.opus','.wv'}

# ─────────────────────────────────────────────
# macOS 드래그앤드롭 — NSApp openFiles 방식
# ─────────────────────────────────────────────
_drop_callback = None   # MainWindow._add_files 로 연결

def setup_macos_drop():
    """
    macOS에서 Finder → 앱으로 드래그할 때 발생하는
    application:openFiles: 이벤트를 pyobjc로 가로챕니다.
    .app으로 패키징 시 Info.plist에 CFBundleDocumentTypes가 있어야
    Finder가 드래그를 허용합니다.
    """
    try:
        import objc
        from AppKit import NSApplication, NSObject

        class _Delegate(NSObject):
            @objc.python_method
            def application_openFiles_(self, app, filenames):
                if _drop_callback:
                    paths = [str(f) for f in filenames]
                    audio = [p for p in paths
                             if os.path.splitext(p)[1].lower() in AUDIO_EXTS]
                    if audio:
                        _drop_callback(audio)

        ns_app = NSApplication.sharedApplication()
        delegate = _Delegate.alloc().init()
        ns_app.setDelegate_(delegate)
        # Dock 아이콘 + 메뉴바 표시 (Regular app)
        ns_app.setActivationPolicy_(0)  # NSApplicationActivationPolicyRegular
        return True
    except Exception as e:
        print(f'[macOS drop] 비활성: {e}')
        return False


# ─────────────────────────────────────────────
# 오디오 로더
# ─────────────────────────────────────────────
def load_audio(filepath):
    try:
        import soundfile as sf
        data, sr = sf.read(filepath, dtype='float32', always_2d=True)
        info = sf.info(filepath)
        bits = _bits_from_subtype(info.subtype)
        return sr, data.mean(axis=1), bits, sr
    except Exception:
        pass
    try:
        from pydub import AudioSegment
        seg = AudioSegment.from_file(filepath)
        sr = seg.frame_rate
        bits = seg.sample_width * 8
        samples = np.array(seg.get_array_of_samples(), dtype=np.float32)
        if seg.channels > 1:
            samples = samples.reshape(-1, seg.channels).mean(axis=1)
        samples /= float(2 ** (bits - 1))
        return sr, samples, bits, sr
    except Exception as e:
        raise RuntimeError(str(e))


def _bits_from_subtype(s):
    for k,v in [('PCM_16',16),('PCM_24',24),('PCM_32',32),
                ('FLOAT',32),('DOUBLE',64),('PCM_S8',8),('PCM_U8',8)]:
        if k in s: return v
    return None


# ─────────────────────────────────────────────
# 분석 엔진
# ─────────────────────────────────────────────
FFT_SIZE = 32768

def analyze(sr, samples, bits, dsr):
    n = len(samples)
    if n > FFT_SIZE * 4:
        mid = n // 2
        chunk = samples[mid - FFT_SIZE*2 : mid + FFT_SIZE*2]
    else:
        chunk = samples

    win = np.hanning(len(chunk))
    spec = np.abs(np.fft.rfft(chunk * win))
    freqs = np.fft.rfftfreq(len(chunk), d=1.0/sr)

    eps = 1e-12
    pdb = 20.0 * np.log10(np.maximum(spec, eps))
    mdb = pdb.max()

    valid = pdb >= mdb - 70.0
    cidx = np.where(valid)[0][-1] if valid.any() else -1
    cutoff = float(freqs[cidx])

    lin = spec ** 2
    cum = np.cumsum(lin)
    if cum[-1] > 0: cum /= cum[-1]
    f99 = float(freqs[min(np.searchsorted(cum, 0.99), len(freqs)-1)])

    noise = float(np.median(np.sort(pdb)[:max(1, len(pdb)//10)]))
    dr = float(mdb - noise)

    nyq = sr / 2.0
    ratio = cutoff / nyq if nyq > 0 else 0
    verdict, color, detail = _judge(dsr, bits, cutoff, nyq, ratio)

    return dict(freqs=freqs, pdb=pdb, mdb=mdb, cutoff=cutoff,
                nyq=nyq, ratio=ratio, cum=cum, f99=f99, dr=dr,
                dsr=dsr, bits=bits, sr=sr,
                verdict=verdict, color=color, detail=detail)


def _judge(dsr, bits, cutoff, nyq, ratio):
    hi = dsr and dsr > 48000
    if hi and cutoff <= 22500:
        return ('가짜 (업스케일 의심)', RED,
                f'선언 SR {dsr//1000}kHz이나 실제 컷오프 {cutoff/1000:.1f}kHz — 업샘플링 의심')
    if ratio >= 0.85:
        return ('진본', GREEN,
                f'컷오프 {cutoff/1000:.1f}kHz (나이퀴스트 대비 {ratio*100:.0f}%) — 선언 품질과 일치')
    if ratio >= 0.65:
        return ('의심', ORANGE,
                f'컷오프 {cutoff/1000:.1f}kHz (나이퀴스트 대비 {ratio*100:.0f}%) — 일부 고주파 손실')
    return ('의심 (업스케일 가능성)', RED,
            f'컷오프 {cutoff/1000:.1f}kHz (나이퀴스트 대비 {ratio*100:.0f}%) — 실제 대역폭 낮음')


# ─────────────────────────────────────────────
# 분석 워커
# ─────────────────────────────────────────────
class Worker(QThread):
    done  = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            sr, samples, bits, dsr = load_audio(self.path)
            self.done.emit(analyze(sr, samples, bits, dsr))
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────
# 차트 위젯 (Canvas)
# ─────────────────────────────────────────────
def _freq_x(f, nyq, x0, w):
    if f <= 0 or nyq <= 0: return x0
    lmin, lmax = math.log10(20), math.log10(nyq)
    t = (math.log10(max(f, 20)) - lmin) / max(lmax - lmin, 1e-9)
    return x0 + t * w


class SpecChart(QWidget):
    def __init__(self):
        super().__init__()
        self.data = None
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, d): self.data = d; self.update()

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        pl, pr, pt, pb = 58, 15, 22, 34
        pw, ph = W-pl-pr, H-pt-pb
        p.fillRect(0,0,W,H, QColor(BG))

        if not self.data:
            p.setPen(QColor(TXT_SUB)); p.setFont(QFont('Arial',11))
            p.drawText(0,0,W,H, Qt.AlignmentFlag.AlignCenter, '파일을 선택하거나 드래그하세요')
            return

        freqs = self.data['freqs']; pdb = self.data['pdb']
        mdb = self.data['mdb']; cutoff = self.data['cutoff']; nyq = self.data['nyq']
        db_min, db_max = mdb-100, mdb

        def dy(db):
            t = (db-db_min)/max(db_max-db_min,1e-9)
            return pt+(1-t)*ph

        GRID_C = QColor('#1e1e33')
        for gf in [20,50,100,200,500,1000,2000,5000,10000,20000,40000,96000]:
            if gf > nyq*1.05: break
            gx = _freq_x(gf, nyq, pl, pw)
            p.setPen(QPen(GRID_C,1)); p.drawLine(int(gx),pt,int(gx),pt+ph)
            p.setPen(QColor(TXT_SUB)); p.setFont(QFont('Arial',8))
            lbl = f'{gf//1000}k' if gf>=1000 else str(gf)
            p.drawText(int(gx)-14, pt+ph+3, 28, 16, Qt.AlignmentFlag.AlignHCenter, lbl)

        for off in range(0,-110,-20):
            gy = dy(mdb+off)
            p.setPen(QPen(GRID_C,1)); p.drawLine(pl,int(gy),pl+pw,int(gy))
            p.setPen(QColor(TXT_SUB)); p.setFont(QFont('Arial',8))
            p.drawText(0,int(gy)-8,pl-4,16,
                       Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter, str(off))

        step = max(1, len(freqs)//pw)
        pts = []
        for i in range(0,len(freqs),step):
            f = freqs[i]
            if f<20 or f>nyq: continue
            pts.append((_freq_x(f,nyq,pl,pw), max(pt,min(pt+ph,dy(float(pdb[i]))))))

        if len(pts)>=2:
            from PyQt6.QtCore import QPointF
            from PyQt6.QtGui import QPolygonF
            poly = [QPointF(pts[0][0],pt+ph)] + [QPointF(x,y) for x,y in pts] + [QPointF(pts[-1][0],pt+ph)]
            g = QLinearGradient(0,pt,0,pt+ph)
            g.setColorAt(0,QColor(80,120,255,150)); g.setColorAt(1,QColor(20,40,120,20))
            p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygonF(poly))
            p.setPen(QPen(QColor(ACCENT),1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(len(pts)-1):
                p.drawLine(QPointF(*pts[i]), QPointF(*pts[i+1]))

        cx = _freq_x(cutoff,nyq,pl,pw)
        p.setPen(QPen(QColor('#ff4488'),1.5,Qt.PenStyle.DashLine))
        p.drawLine(int(cx),pt,int(cx),pt+ph)
        p.setPen(QColor('#ff4488')); p.setFont(QFont('Arial',8))
        lx = int(cx)-84 if cx+80>W-pr else int(cx)+4
        p.drawText(lx,pt+3,80,14,Qt.AlignmentFlag.AlignLeft,f'컷오프 {cutoff/1000:.1f}k')

        p.setPen(QPen(QColor('#333355'),1))
        p.drawRect(pl,pt,pw,ph)
        p.setPen(QColor(TXT_SUB)); p.setFont(QFont('Arial',9))
        p.drawText(pl,2,pw,pt,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,'주파수 스펙트럼 (dB)')


class EnergyChart(QWidget):
    def __init__(self):
        super().__init__()
        self.data = None
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, d): self.data = d; self.update()

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        pl, pr, pt, pb = 58, 15, 22, 34
        pw, ph = W-pl-pr, H-pt-pb
        p.fillRect(0,0,W,H,QColor(BG))
        if not self.data: return

        freqs=self.data['freqs']; cum=self.data['cum']
        nyq=self.data['nyq']; f99=self.data['f99']

        def cy(pct): return pt+(1-pct)*ph
        GRID_C = QColor('#1e1e33')

        for gf in [20,50,100,200,500,1000,2000,5000,10000,20000,40000,96000]:
            if gf>nyq*1.05: break
            gx=_freq_x(gf,nyq,pl,pw)
            p.setPen(QPen(GRID_C,1)); p.drawLine(int(gx),pt,int(gx),pt+ph)
            p.setPen(QColor(TXT_SUB)); p.setFont(QFont('Arial',8))
            lbl=f'{gf//1000}k' if gf>=1000 else str(gf)
            p.drawText(int(gx)-14,pt+ph+3,28,16,Qt.AlignmentFlag.AlignHCenter,lbl)

        for pct in [0,25,50,75,99,100]:
            gy=cy(pct/100)
            p.setPen(QPen(GRID_C,1)); p.drawLine(pl,int(gy),pl+pw,int(gy))
            p.setPen(QColor(TXT_SUB)); p.setFont(QFont('Arial',8))
            p.drawText(0,int(gy)-8,pl-4,16,
                       Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,f'{pct}%')

        step=max(1,len(freqs)//pw)
        pts=[]
        for i in range(0,len(freqs),step):
            f=freqs[i]
            if f<20 or f>nyq: continue
            pts.append((_freq_x(f,nyq,pl,pw), max(pt,min(pt+ph,cy(float(cum[i]))))))

        if len(pts)>=2:
            from PyQt6.QtCore import QPointF
            from PyQt6.QtGui import QPolygonF
            poly=[QPointF(pts[0][0],pt+ph)]+[QPointF(x,y) for x,y in pts]+[QPointF(pts[-1][0],pt+ph)]
            g=QLinearGradient(0,pt,0,pt+ph)
            g.setColorAt(0,QColor(0,220,180,130)); g.setColorAt(1,QColor(0,80,60,20))
            p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygonF(poly))
            p.setPen(QPen(QColor('#00e0b0'),1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(len(pts)-1):
                p.drawLine(QPointF(*pts[i]),QPointF(*pts[i+1]))

        x99=_freq_x(f99,nyq,pl,pw)
        p.setPen(QPen(QColor('#ffcc00'),1.2,Qt.PenStyle.DashLine))
        p.drawLine(int(x99),pt,int(x99),pt+ph)
        p.setPen(QColor('#ffcc00')); p.setFont(QFont('Arial',8))
        p.drawText(int(x99)+3,pt+3,80,14,Qt.AlignmentFlag.AlignLeft,f'99%: {f99/1000:.1f}k')

        p.setPen(QPen(QColor('#333355'),1)); p.drawRect(pl,pt,pw,ph)
        p.setPen(QColor(TXT_SUB)); p.setFont(QFont('Arial',9))
        p.drawText(pl,2,pw,pt,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,'누적 에너지 분포')


# ─────────────────────────────────────────────
# 메인 윈도우
# ─────────────────────────────────────────────
class MainWindow(QMainWindow):
    # NSApp에서 파일 열기 이벤트를 받기 위한 시그널
    open_files_signal = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('니콘 친게 음원 감별사')
        self.setMinimumSize(1000, 650)
        self.resize(1280, 800)
        self.setAcceptDrops(True)
        self._workers = {}
        self._files = []   # [(name, path)]
        self._result = None
        self._apply_style()
        self._build_ui()
        self.open_files_signal.connect(self._add_files)

    def _apply_style(self):
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window,      QColor(BG))
        pal.setColor(QPalette.ColorRole.WindowText,  QColor(TXT))
        pal.setColor(QPalette.ColorRole.Base,        QColor(PANEL))
        pal.setColor(QPalette.ColorRole.Text,        QColor(TXT))
        pal.setColor(QPalette.ColorRole.Button,      QColor(CARD))
        pal.setColor(QPalette.ColorRole.ButtonText,  QColor(TXT))
        pal.setColor(QPalette.ColorRole.Highlight,   QColor(ACCENT))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor('#fff'))
        QApplication.setPalette(pal)

    def _build_ui(self):
        c = QWidget(); self.setCentralWidget(c)
        root = QVBoxLayout(c); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # 헤더
        hdr = QWidget(); hdr.setFixedHeight(52)
        hdr.setStyleSheet(f'background:{BG}; border-bottom:1px solid #1a1a33;')
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20,0,20,0)
        t = QLabel('니콘 친게 음원 감별사')
        t.setStyleSheet(f'color:{TXT}; font-size:18px; font-weight:700;')
        hl.addWidget(t); hl.addStretch()
        s = QLabel('주파수 스펙트럼 기반 음원 진위 분석기')
        s.setStyleSheet(f'color:{TXT_SUB}; font-size:11px;')
        hl.addWidget(s)
        root.addWidget(hdr)

        sp = QSplitter(Qt.Orientation.Horizontal)
        sp.setHandleWidth(1)
        sp.setStyleSheet('QSplitter::handle{background:#1a1a33;}')
        root.addWidget(sp, 1)

        # ── 왼쪽 ──
        left = QWidget(); left.setMinimumWidth(220); left.setMaximumWidth(300)
        left.setStyleSheet(f'background:{PANEL};')
        ll = QVBoxLayout(left); ll.setContentsMargins(12,14,12,14); ll.setSpacing(8)

        QL = QLabel('파일 대기열')
        QL.setStyleSheet(f'color:{TXT_SUB}; font-size:10px; font-weight:600; letter-spacing:1px;')
        ll.addWidget(QL)

        self.flist = QListWidget()
        self.flist.setStyleSheet(f'''
            QListWidget{{background:{CARD};border:1px solid #1e1e3a;border-radius:6px;
                color:{TXT};font-size:12px;outline:none;}}
            QListWidget::item{{padding:8px 10px;border-bottom:1px solid #1a1a33;}}
            QListWidget::item:selected{{background:{ACCENT};color:#fff;}}
            QListWidget::item:hover{{background:#1e1e3a;}}
        ''')
        self.flist.setAcceptDrops(False)
        self.flist.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.flist.currentRowChanged.connect(self._on_row)
        ll.addWidget(self.flist, 1)

        hint = QLabel('↑ 파일을 드래그하거나\n아래 버튼으로 추가하세요\nFLAC·WAV·MP3·AIFF·OGG·M4A')
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f'color:{TXT_SUB}; font-size:9px; padding:4px;')
        ll.addWidget(hint)

        br = QHBoxLayout()
        ba = QPushButton('+ 파일 추가')
        ba.clicked.connect(self._open_files)
        ba.setStyleSheet(f'''QPushButton{{background:{ACCENT};color:#fff;border:none;
            border-radius:5px;padding:7px 12px;font-size:12px;font-weight:600;}}
            QPushButton:hover{{background:#7799ff;}}''')
        bc = QPushButton('지우기')
        bc.clicked.connect(self._clear)
        bc.setStyleSheet(f'''QPushButton{{background:#1e1e3a;color:{TXT_SUB};
            border:1px solid #2a2a4a;border-radius:5px;padding:7px 8px;font-size:11px;}}
            QPushButton:hover{{background:#2a2a4a;color:{TXT};}}''')
        br.addWidget(ba); br.addWidget(bc)
        ll.addLayout(br)
        sp.addWidget(left)

        # ── 오른쪽 ──
        rsc = QScrollArea(); rsc.setWidgetResizable(True)
        rsc.setStyleSheet(f'QScrollArea{{background:{BG};border:none;}}')
        right = QWidget(); right.setStyleSheet(f'background:{BG};')
        rl = QVBoxLayout(right); rl.setContentsMargins(18,16,18,18); rl.setSpacing(10)

        # 정보 카드
        ic = self._card()
        icl = QVBoxLayout(ic); icl.setContentsMargins(14,10,14,10); icl.setSpacing(4)
        self.fname_lbl = QLabel('파일을 선택하거나 드래그해서 분석을 시작하세요')
        self.fname_lbl.setStyleSheet(f'color:{TXT};font-size:13px;font-weight:700;')
        self.fname_lbl.setWordWrap(True)
        icl.addWidget(self.fname_lbl)
        mr = QHBoxLayout()
        self._meta = {}
        for k in ['SR','비트','나이퀴스트','컷오프','다이나믹']:
            lbl = QLabel(f'{k}: —')
            lbl.setStyleSheet(f'color:{TXT};font-size:10px;background:#1a1a33;border-radius:4px;padding:3px 7px;')
            mr.addWidget(lbl); self._meta[k] = lbl
        mr.addStretch(); icl.addLayout(mr)
        rl.addWidget(ic)

        # 판정 카드
        vc = self._card()
        vcl = QVBoxLayout(vc); vcl.setContentsMargins(14,10,14,10); vcl.setSpacing(2)
        QLabel('판정 결과', styleSheet=f'color:{TXT_SUB};font-size:10px;font-weight:600;').setParent(vc)
        vcl.addWidget(QLabel('판정 결과', styleSheet=f'color:{TXT_SUB};font-size:10px;font-weight:600;letter-spacing:1px;'))
        self.verdict_lbl = QLabel('—')
        self.verdict_lbl.setStyleSheet('color:#888;font-size:22px;font-weight:800;')
        vcl.addWidget(self.verdict_lbl)
        self.detail_lbl = QLabel('—')
        self.detail_lbl.setStyleSheet(f'color:{TXT_SUB};font-size:11px;')
        self.detail_lbl.setWordWrap(True)
        vcl.addWidget(self.detail_lbl)
        rl.addWidget(vc)

        # 프로그레스
        self.prog = QProgressBar()
        self.prog.setRange(0,100); self.prog.setValue(0)
        self.prog.setFixedHeight(3); self.prog.setVisible(False)
        self.prog.setStyleSheet(f'QProgressBar{{background:#1a1a33;border:none;border-radius:2px;}}'
                                f'QProgressBar::chunk{{background:{ACCENT};border-radius:2px;}}')
        rl.addWidget(self.prog)

        self.spec = SpecChart(); rl.addWidget(self.spec)
        self.eng  = EnergyChart(); rl.addWidget(self.eng)
        rl.addStretch()

        rsc.setWidget(right); sp.addWidget(rsc)
        sp.setSizes([240, 1040])

    def _card(self):
        f = QFrame()
        f.setStyleSheet(f'QFrame{{background:{CARD};border:1px solid #1e1e3a;border-radius:8px;}}')
        return f

    # ── 드래그앤드롭 (PyQt 레벨) ──────────────
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
        else: e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
        else: e.ignore()

    def dropEvent(self, e):
        paths = []
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if os.path.isfile(p) and os.path.splitext(p)[1].lower() in AUDIO_EXTS:
                paths.append(p)
            elif os.path.isdir(p):
                for root, _, files in os.walk(p):
                    for f in sorted(files):
                        if os.path.splitext(f)[1].lower() in AUDIO_EXTS:
                            paths.append(os.path.join(root, f))
        if paths: self._add_files(paths)
        e.acceptProposedAction()

    # ── 파일 관리 ─────────────────────────────
    def _open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, '오디오 파일 선택', '',
            'Audio (*.flac *.wav *.aiff *.aif *.ogg *.mp3 *.m4a *.aac *.opus *.wv);;All (*)')
        if paths: self._add_files(paths)

    def _add_files(self, paths):
        existing = {p for _,p in self._files}
        for p in paths:
            if p not in existing:
                name = os.path.basename(p)
                self._files.append((name, p))
                self.flist.addItem(f'  {name}')
                existing.add(p)
        if self.flist.currentRow() < 0 and self.flist.count() > 0:
            self.flist.setCurrentRow(0)

    def _clear(self):
        self._files.clear(); self.flist.clear()
        self._result = None
        self.spec.set_data(None); self.eng.set_data(None)
        self.fname_lbl.setText('파일을 선택하거나 드래그해서 분석을 시작하세요')
        self.verdict_lbl.setText('—'); self.verdict_lbl.setStyleSheet('color:#888;font-size:22px;font-weight:800;')
        self.detail_lbl.setText('—')

    def _on_row(self, row):
        if row < 0 or row >= len(self._files): return
        name, path = self._files[row]
        self.fname_lbl.setText(name)
        self.verdict_lbl.setText('분석 중…')
        self.verdict_lbl.setStyleSheet(f'color:{TXT_SUB};font-size:22px;font-weight:800;')
        self.detail_lbl.setText('')
        self.prog.setValue(0); self.prog.setVisible(True)
        w = Worker(path)
        w.done.connect(self._on_result); w.error.connect(self._on_error)
        self._workers[path] = w; w.start()

    def _on_result(self, r):
        self._result = r; self.prog.setVisible(False)
        dsr = r['dsr']; sr = r['sr']
        self._meta['SR'].setText(f"SR: {(dsr or sr)//1000}kHz")
        self._meta['비트'].setText(f"비트: {r['bits']}bit" if r['bits'] else "비트: —")
        self._meta['나이퀴스트'].setText(f"나이퀴스트: {r['nyq']/1000:.0f}kHz")
        self._meta['컷오프'].setText(f"컷오프: {r['cutoff']/1000:.1f}kHz")
        self._meta['다이나믹'].setText(f"다이나믹: {r['dr']:.0f}dB")
        self.verdict_lbl.setText(r['verdict'])
        self.verdict_lbl.setStyleSheet(f"color:{r['color']};font-size:22px;font-weight:800;")
        self.detail_lbl.setText(r['detail'])
        self.spec.set_data(r); self.eng.set_data(r)

    def _on_error(self, msg):
        self.prog.setVisible(False)
        self.verdict_lbl.setText('오류'); self.verdict_lbl.setStyleSheet(f'color:{RED};font-size:22px;font-weight:800;')
        self.detail_lbl.setText(msg)


# ─────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────
def main():
    global _drop_callback
    app = QApplication(sys.argv)
    app.setApplicationName('니콘 친게 음원 감별사')
    app.setStyle('Fusion')

    win = MainWindow()

    # macOS NSApp 드래그앤드롭 연결
    def _ns_open(paths):
        win.open_files_signal.emit(paths)
    _drop_callback = _ns_open
    setup_macos_drop()

    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
