"""Open-document selector; labels are presentation, item data is an exact UID."""
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QListWidget,QListWidgetItem,QPushButton,QLabel,QDialogButtonBox
from PyQt6.QtCore import Qt
from .channel_snapshots import documents,mono

class ChannelSelector(QDialog):
    def __init__(self,owner,host,shape):
        super().__init__(owner);self.host=host;self.shape=shape;self.uid=None
        self.setWindowTitle('Canale dal programma ospite');self.resize(640,360)
        root=QVBoxLayout(self);root.addWidget(QLabel('Immagini monocromatiche già allineate alla catena'))
        self.items=QListWidget();root.addWidget(self.items)
        refresh=QPushButton('Aggiorna elenco');refresh.clicked.connect(self.refresh);root.addWidget(refresh)
        self.note=QLabel();self.note.setWordWrap(True);root.addWidget(self.note)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept_selection);self.buttons.rejected.connect(self.reject);root.addWidget(self.buttons)
        self.items.itemDoubleClicked.connect(lambda _:self.accept_selection());self.refresh()
    def refresh(self):
        self.items.clear()
        try:
            for uid,(title,doc) in documents(self.host).items():
                image=getattr(doc,'image',None);shape=getattr(image,'shape',())
                label=f'{title} · {"×".join(map(str,shape))} · UID {uid}'
                item=QListWidgetItem(label);item.setData(Qt.ItemDataRole.UserRole,uid)
                try:mono(image,self.shape)
                except (TypeError,ValueError) as exc:
                    item.setText(label+' · '+str(exc));item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                self.items.addItem(item)
            self.note.setText('La scelta acquisisce copie stabili di tutti i canali selezionati nel programma ospite.')
        except Exception as exc:self.note.setText(str(exc))
    def accept_selection(self):
        item=self.items.currentItem()
        if item is not None and item.flags() & Qt.ItemFlag.ItemIsEnabled:
            self.uid=item.data(Qt.ItemDataRole.UserRole);self.accept()
