"""Compact only horizontal slider rows; leave controls and engines untouched."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSlider,QLabel,QWidget,QBoxLayout,QVBoxLayout,QHBoxLayout,QFormLayout,QGridLayout,QAbstractSpinBox,QPushButton
GAP=2

def slider_widget(widget):
    return isinstance(widget,QSlider) and widget.orientation()==Qt.Orientation.Horizontal or widget is not None and type(widget).__name__=='ColorSlider'

def slider_row(item):
    widget=item.widget();layout=item.layout()
    if slider_widget(widget):return True
    if widget is not None and type(widget).__name__ in ('Control','Fader'):return True
    if isinstance(layout,QHBoxLayout):
        return any(slider_widget(layout.itemAt(i).widget()) or (layout.itemAt(i).widget() is not None and type(layout.itemAt(i).widget()).__name__ in ('Control','Fader')) for i in range(layout.count()))
    return False

def caption(item):
    widget=item.widget()
    return isinstance(widget,QLabel) and not widget.objectName() and not widget.wordWrap() and len(widget.text())<100

def compact_box(layout):
    # A run may include the caption directly attached to a slider. Group layouts,
    # not widgets, so the original palette visibility walker still finds rows.
    items=[layout.itemAt(i) for i in range(layout.count())]
    marked=[slider_row(item) for item in items]
    for i in range(1,len(items)):
        if marked[i] and items[i].layout() is not None and caption(items[i-1]):marked[i-1]=True
    runs=[];start=None
    for i,on in enumerate(marked+[False]):
        if on and start is None:start=i
        if not on and start is not None:
            if i-start>=2:runs.append((start,i))
            start=None
    for first,end in reversed(runs):
        if first==0 and end==layout.count():
            layout.setSpacing(GAP);layout.setAlignment(Qt.AlignmentFlag.AlignTop);continue
        group=QVBoxLayout();group.setContentsMargins(0,0,0,0);group.setSpacing(GAP);group.setAlignment(Qt.AlignmentFlag.AlignTop)
        for _ in range(end-first):
            item=layout.takeAt(first)
            if item.layout() is not None:
                child=item.layout();child.setParent(None);group.addLayout(child)
            else:group.addItem(item)
        layout.insertLayout(first,group)

def compact_form(layout):
    rows=[slider_row(layout.itemAt(i,QFormLayout.ItemRole.FieldRole)) if layout.itemAt(i,QFormLayout.ItemRole.FieldRole) is not None else False for i in range(layout.rowCount())]
    runs=[];start=None
    for i,on in enumerate(rows+[False]):
        if on and start is None:start=i
        if not on and start is not None:
            if i-start>=2:runs.append((start,i))
            start=None
    for first,end in reversed(runs):
        group=QFormLayout();group.setContentsMargins(0,0,0,0);group.setVerticalSpacing(GAP)
        group.setHorizontalSpacing(layout.horizontalSpacing());group.setFieldGrowthPolicy(layout.fieldGrowthPolicy());group.setRowWrapPolicy(layout.rowWrapPolicy());group.setLabelAlignment(layout.labelAlignment());group.setFormAlignment(layout.formAlignment() | Qt.AlignmentFlag.AlignTop)
        for _ in range(end-first):
            row=layout.takeRow(first)
            label=row.labelItem.widget() if row.labelItem is not None else None
            item=row.fieldItem
            if item.layout() is not None:
                child=item.layout();child.setParent(None);group.addRow(label,child)
            else:group.addRow(label,item.widget())
        layout.insertRow(first,group)

def compact_grid(layout):
    rows=[]
    for r in range(layout.rowCount()):
        rows.append(any(layout.itemAtPosition(r,c) is not None and slider_row(layout.itemAtPosition(r,c)) for c in range(layout.columnCount())))
    runs=[];start=None
    for i,on in enumerate(rows+[False]):
        if on and start is None:start=i
        if not on and start is not None:
            if i-start>=2:runs.append((start,i))
            start=None
    for first,end in reversed(runs):
        group=QGridLayout();group.setContentsMargins(0,0,0,0);group.setVerticalSpacing(GAP);group.setHorizontalSpacing(layout.horizontalSpacing());group.setAlignment(Qt.AlignmentFlag.AlignTop)
        # Retain column widths contributed by controls outside the slider run.
        for c in range(layout.columnCount()):
            width=max((layout.itemAtPosition(r,c).sizeHint().width() for r in range(layout.rowCount()) if layout.itemAtPosition(r,c) is not None),default=0) if c==0 else 0
            group.setColumnMinimumWidth(c,width);group.setColumnStretch(c,layout.columnStretch(c))
        for i in reversed(range(layout.count())):
            r,c,rs,cs=layout.getItemPosition(i)
            if first<=r and r+rs<=end:
                item=layout.takeAt(i)
                if item.layout() is not None:
                    child=item.layout();child.setParent(None);group.addLayout(child,r-first,c,rs,cs,item.alignment())
                else:group.addItem(item,r-first,c,rs,cs,item.alignment())
        layout.addLayout(group,first,0,end-first,layout.columnCount())

def compact_sliders(panel):
    if getattr(panel,'_slider_spacing_applied',False):return
    panel._slider_spacing_applied=True
    # Take the original layout inventory before inserting compact sub-layouts.
    layouts=[];seen=set()
    def walk(layout):
        if layout is None or id(layout) in seen:return
        seen.add(id(layout));layouts.append(layout)
        for i in range(layout.count()):
            item=layout.itemAt(i)
            if item.layout() is not None:walk(item.layout())
            if item.widget() is not None:walk(item.widget().layout())
    walk(panel.layout())
    for widget in panel.findChildren(QWidget):walk(widget.layout())
    # A slider row is as tall as its largest readout/button. Remove only their
    # vertical padding; inherited styles otherwise leave 34--38 px tall rows.
    # Use direct row children, never unrelated buttons or fields in the panel.
    for layout in layouts:
        if isinstance(layout,QHBoxLayout) and any(slider_widget(layout.itemAt(i).widget()) for i in range(layout.count())):
            for i in range(layout.count()):
                widget=layout.itemAt(i).widget()
                if isinstance(widget,(QAbstractSpinBox,QPushButton)):
                    style=widget.styleSheet()
                    rule='padding-top:0px; padding-bottom:0px;'
                    if '{' in style:
                        widget.setStyleSheet(style+'\n'+('QAbstractSpinBox' if isinstance(widget,QAbstractSpinBox) else 'QPushButton')+' {'+rule+'}')
                    else:widget.setStyleSheet(style+';'+rule)
    for layout in reversed(layouts):
        if isinstance(layout,QFormLayout):compact_form(layout)
        elif isinstance(layout,QGridLayout):compact_grid(layout)
        elif isinstance(layout,QVBoxLayout):compact_box(layout)
    # Zero only vertical padding inside single-slider rows; preserve horizontal gaps.
    for layout in layouts:
        if isinstance(layout,QHBoxLayout) and any(slider_widget(layout.itemAt(i).widget()) for i in range(layout.count())):
            margins=layout.contentsMargins();layout.setContentsMargins(margins.left(),0,margins.right(),0)
