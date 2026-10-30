"""Permanent floating inspectors, including macOS tool-window visibility."""
from PyQt6 import sip
from PyQt6.QtCore import Qt,QObject,QEvent,QTimer
from PyQt6.QtWidgets import QApplication

class ForegroundGuard(QObject):
    def __init__(self,panel):
        super().__init__(panel);self.panel=panel;self.owner=panel.parentWidget()
        self.pending=False
        if self.owner is not None:self.owner.installEventFilter(self)
        app=QApplication.instance()
        if app is not None:app.applicationStateChanged.connect(self.application_changed)
    def application_changed(self,state):
        if state==Qt.ApplicationState.ApplicationActive:self.schedule()
    def eventFilter(self,watched,event):
        if watched is self.owner and event.type() in (QEvent.Type.WindowActivate,QEvent.Type.Show,QEvent.Type.WindowStateChange):self.schedule()
        return False
    def schedule(self):
        if not self.pending:
            self.pending=True;QTimer.singleShot(0,self.restore_order)
    def restore_order(self):
        self.pending=False
        # Never resurrect a closed inspector or change keyboard focus.
        if sip.isdeleted(self.panel) or self.owner is None or sip.isdeleted(self.owner):return
        if self.panel.isVisible() and self.owner.isVisible() and not self.owner.isMinimized():self.panel.raise_()

def keep_in_front(panel):
    # Set before the native NSPanel is created. Topmost level alone does not
    # disable macOS hiding tool windows when the application deactivates.
    panel.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow,True)
    panel.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,True)
    panel.setModal(False)
    if not hasattr(panel,'_foreground_guard'):panel._foreground_guard=ForegroundGuard(panel)
