"""Serial node editor. Every graph edit updates the processing chain."""
from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer
from PyQt6.QtGui import QColor, QPen, QBrush, QFont, QPainter, QPainterPath, QLinearGradient
from .instrument_style import paint_metal, draw_module_icon
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QMenu, QGraphicsRectItem, QGraphicsItem, QGraphicsObject, QGraphicsPathItem

MODULE_CATALOG=(('syqon','SyQon'),('masks','Masks'),('separate_stars','Separate Stars…'),('recombine_stars','Recombine Stars…'),('stretch','Stretch'),('hdr_fusion','HDR Fusion'),('clahe','CLAHE'),('palette_native','Palette Studio'),('background_neutralization','Background Neutralization'),('ghs','Adaptive GHS Stretch'),('statistical','Statistical Stretch'),('eq','Spatial Equalizer'),('compressor','Multiband Compressor'),('parametric','Astro Parametric Equalizer'),('filament','Nebula Filament Enhancer'),('colors','Nebula Colors & Tone'),('curves','Curves'),('freeze','Freeze · native checkpoint'))

class Port(QGraphicsObject):
    def __init__(self,node,direction):
        super().__init__(node);self.node=node;self.direction=direction
        self.setPos(135,76 if direction=='out' else 0);self.setZValue(5)
        self.setCursor(Qt.CursorShape.CrossCursor);self.setToolTip('Drag to an input port' if direction=='out' else 'Input port')
    def boundingRect(self):return QRectF(-9,-9,18,18)
    def paint(self,painter,option,widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing);painter.setPen(QPen(QColor(self.node.accent),1.8));painter.setBrush(QColor('#111b29'));painter.drawEllipse(QRectF(-4,-4,8,8))
    def mousePressEvent(self,event):self.node.canvas.begin_cable(self);event.accept()
    def mouseMoveEvent(self,event):self.node.canvas.drag_cable(event.scenePos());event.accept()
    def mouseReleaseEvent(self,event):self.node.canvas.end_cable(event.scenePos());event.accept()

class Cable(QGraphicsPathItem):
    def __init__(self,canvas,edge,path,pen):
        super().__init__(path);self.canvas=canvas;self.edge=edge;self.setPen(pen);self.setZValue(0)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable);self.setToolTip('Right-click: insert a module here or disconnect · Delete: disconnect')
    def paint(self,painter,option,widget=None):
        if self.isSelected():painter.setPen(QPen(QColor('#f1767c'),4));painter.drawPath(self.path())
        else:super().paint(painter,option,widget)
    def shape(self):
        from PyQt6.QtGui import QPainterPathStroker
        stroker=QPainterPathStroker();stroker.setWidth(12);return stroker.createStroke(self.path())

class BypassButton(QGraphicsObject):
    def __init__(self,node):
        super().__init__(node);self.node=node;self.checked=False;self.setPos(181,45)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton);self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Bypass: skip this module while preserving its settings')
    def boundingRect(self):return QRectF(0,0,78,22)
    def paint(self,painter,option,widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_metal(painter,self.boundingRect(),'footer',3)
        painter.setPen(QPen(QColor('#d49a38' if self.checked else '#65777d'),.8))
        painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawRoundedRect(self.boundingRect().adjusted(.5,.5,-.5,-.5),3,3)
        painter.setPen(QColor('#f3c86b' if self.checked else '#c2d2d7'));painter.setFont(QFont('Arial',9,QFont.Weight.DemiBold))
        painter.drawText(self.boundingRect(),Qt.AlignmentFlag.AlignCenter,'BYPASS')
    def mousePressEvent(self,event):event.accept()
    def mouseReleaseEvent(self,event):
        if self.boundingRect().contains(event.pos()) and self.node.canvas.on_bypass:
            self.node.canvas.on_bypass(self.node.key,not self.checked)
        event.accept()
    def mouseDoubleClickEvent(self,event):event.accept()

class Node(QGraphicsRectItem):
    def __init__(self, canvas, key, title, permanent=False, kind=None, serial=0):
        super().__init__(0,0,250,54)
        self.canvas, self.key, self.permanent = canvas, key, permanent
        self.kind=kind;self.serial=serial
        self.setRect(0,0,270,76)
        self.title = title
        self.freeze_label='LIVE'
        self.bypassed=False
        self.compatibility='unknown';self.requirement='linear' if kind in ('ghs','statistical','hdr_fusion') else 'nonlinear' if kind=='clahe' else 'either' if kind in ('eq','compressor','parametric','filament','palette','colors','curves','freeze','palette_native','stretch','separate_stars','recombine_stars','masks','syqon','background_neutralization') else None
        self.bypass_button=BypassButton(self) if not permanent else None
        self.in_port=Port(self,'in') if key!='input' else None
        self.out_port=Port(self,'out') if key!='output' else None
        self.accent = '#249d90' if key == 'input' else '#d59b42' if key == 'output' else '#58c9b5' if kind in ('ghs','statistical','stretch') else '#72aaff'
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setAcceptHoverEvents(True)
        self.hovered = False
        self.setZValue(2)
        self.setToolTip('Double-click: controls' if permanent else 'Drag to move · double-click: floating controls')
    def hoverEnterEvent(self,event):
        self.hovered=True;self.update();super().hoverEnterEvent(event)
    def hoverLeaveEvent(self,event):
        self.hovered=False;self.update();super().hoverLeaveEvent(event)
    def paint(self,painter,option,widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.bypassed:painter.setOpacity(.55)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0,0,0,100));painter.drawRoundedRect(QRectF(1,3,270,76),5,5)
        paint_metal(painter,self.rect(),'node',5)
        edge='#f1767c' if self.compatibility=='invalid' else self.accent if self.isSelected() or self.hovered else '#798b91'
        painter.setPen(QPen(QColor(edge),1.1));painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(.6,.6,-.6,-.6),5,5)
        painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor(self.accent));painter.drawRoundedRect(QRectF(1.5,9,3,58),1.5,1.5)
        paint_metal(painter,QRectF(13,17,40,42),'well',4)
        draw_module_icon(painter,self.key if self.permanent else self.kind,self.accent)
        painter.setPen(QColor('#e1e8f3'));painter.setFont(QFont('Arial',11,QFont.Weight.DemiBold))
        name='SyQon' if self.kind=='syqon' else 'INPUT' if self.key=='input' else 'OUTPUT' if self.key=='output' else 'Masks' if self.kind=='masks' else 'Background Neutralization' if self.kind=='background_neutralization' else 'Palette Studio' if self.kind=='palette_native' else 'Recombine Stars' if self.kind=='recombine_stars' else 'Separate Stars' if self.kind=='separate_stars' else 'Stretch' if self.kind=='stretch' else 'HDR Fusion' if self.kind=='hdr_fusion' else 'Statistical Stretch' if self.kind=='statistical' else 'Adaptive GHS' if self.kind=='ghs' else 'Compressor' if self.kind=='compressor' else 'Parametric EQ' if self.kind=='parametric' else 'Nebula Filament' if self.kind=='filament' else 'Nebula Palette' if self.kind=='palette' else 'Nebula Colors' if self.kind=='colors' else 'Freeze' if self.kind=='freeze' else 'CLAHE' if self.kind=='clahe' else 'Curves' if self.kind=='curves' else 'Spatial Equalizer'
        painter.drawText(QRectF(64,17,192,23),name)
        painter.setFont(QFont('Arial',9));painter.setPen(QColor('#adbdc5'))
        subtitle='Original data · no stretch' if self.key=='input' else 'Rendering and export' if self.key=='output' else ({'linear':'Linear','nonlinear':'Non-linear','either':'Both'}[self.requirement]+' · '+str(self.serial).zfill(2))
        if self.kind=='freeze':subtitle=self.freeze_label+' · '+str(self.serial).zfill(2)
        painter.drawText(QRectF(64,43,190 if self.permanent else 110,20),subtitle)
    def set_compatibility(self,requirement,status):
        self.requirement=requirement;self.compatibility=status
        self.accent={'linear':'#58c9b5','nonlinear':'#e7b565','either':'#72aaff'}[requirement]
        explanation={'invalid':'INCOMPATIBLE INPUT: an active stretch is required before this module.','skipped':'Already non-linear: GHS automatically skipped.','unknown':'Confirm the image data state in the preview.','ok':'Compatible input.','bypass':'Module manually bypassed.'}[status]
        if status=='skipped' and self.kind=='statistical':explanation='Already non-linear: Statistical Stretch automatically skipped.'
        self.setToolTip(explanation+' Double-click: controls · drag: move · Delete: remove')
        self.update()
    def set_bypass(self,value):
        self.bypassed=value
        if self.bypass_button:self.bypass_button.checked=value;self.bypass_button.update()
        self.update()
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and hasattr(self.canvas,'cables'):
            self.canvas.request_visual_update()
        return super().itemChange(change,value)
    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        self.canvas.reorder()
    def mouseDoubleClickEvent(self,event):
        self.canvas.open_panel(self.key);event.accept()

class NodeCanvas(QGraphicsView):
    TOP_Y=16
    FIRST_Y=110
    PITCH=94
    def __init__(self, open_panel, parent=None, on_add=None, on_change=None, on_remove=None, on_bypass=None):
        super().__init__(parent)
        self.open_panel=open_panel; self.modules=[]; self.cables=[]; self.serial=0
        self.edges=[('input','output')];self.drag_port=None;self.drag_line=None;self.connection_error=''
        self.on_add=on_add;self.on_change=on_change;self.on_remove=on_remove;self.on_bypass=on_bypass
        self.setScene(QGraphicsScene(self));self.scene().setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex);self.scene().setSceneRect(0,0,440,650)
        self._visual_timer=QTimer(self);self._visual_timer.setSingleShot(True);self._visual_timer.timeout.connect(self.flush_visual_update)
        self._resize_timer=QTimer(self);self._resize_timer.setSingleShot(True);self._resize_timer.timeout.connect(self.fit_width)
        self._fitting=False
        self.setRenderHint(QPainter.RenderHint.Antialiasing);self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundBrush(QColor('#0d1421'));self.setMinimumWidth(280)
        self.input=Node(self,'input','INPUT · GHS',True);self.scene().addItem(self.input);self.input.setPos(85,self.TOP_Y)
        self.output=Node(self,'output','OUTPUT',True);self.scene().addItem(self.output);self.output.setPos(85,self.FIRST_Y+2*self.PITCH)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignTop)
        self.update_cables()
    def note(self,text,x,y,size=10,color='#94a4bb'):
        t=self.scene().addText(text,QFont('Arial',size));t.setDefaultTextColor(QColor(color));t.setPos(x,y)
    def add_module(self,kind='eq',identifier=None,position=None,edge=None):
        import uuid
        if kind not in ('background_neutralization','syqon','hdr_fusion','separate_stars','recombine_stars','clahe','statistical','ghs','eq','compressor','parametric','filament','palette','colors','curves','freeze','palette_native','stretch','masks'):raise ValueError('Unsupported module')
        if edge is not None:
            edge=tuple(edge)
            if edge not in self.edges:raise ValueError('The selected cable no longer exists')
            position=self.insertion_position(edge,position)
        self.connection_error=''
        self.serial+=1
        node=Node(self,identifier or str(uuid.uuid4()),kind,kind=kind,serial=self.serial)
        self.scene().addItem(node);self.modules.append(node)
        if position is None:
            position=QPointF(85,self.FIRST_Y+(len(self.modules)-1)*self.PITCH)
            while any(QRectF(position,QRectF(0,0,270,76).size()).intersects(other.sceneBoundingRect().adjusted(-8,-8,8,8)) for other in [self.input,self.output]+self.modules[:-1]):position+=QPointF(300,0)
        node.setPos(position)
        incoming=edge if edge is not None else next((cable for cable in self.edges if cable[1]=='output'),None)
        if incoming:
            self.edges.remove(incoming);self.edges.extend([(incoming[0],node.key),(node.key,incoming[1])])
        if self.on_add:self.on_add(node)
        self.update_cables();self.fit_width()
        return node
    def insertion_position(self,edge,position=None):
        nodes={n.key:n for n in [self.input]+self.modules+[self.output]};source=nodes[edge[0]];target=nodes[edge[1]]
        if position is None:position=(source.pos()+QPointF(135,76)+target.pos()+QPointF(135,0))*.5
        position=QPointF(position)-QPointF(135,38)
        proposed=QRectF(position,QRectF(0,0,270,76).size())
        if proposed.intersects(source.sceneBoundingRect().adjusted(-8,-8,8,8)):
            position.setY(source.pos().y()+self.PITCH);proposed.moveTop(position.y())
        if proposed.adjusted(-8,-8,8,8).intersects(target.sceneBoundingRect()):
            shift=max(self.PITCH,proposed.bottom()+18-target.pos().y());links=dict(self.edges);key=edge[1];seen=set()
            while key in nodes and key not in seen:
                seen.add(key);nodes[key].setPos(nodes[key].pos()+QPointF(0,shift));key=links.get(key)
        return position
    def insert_module(self,kind,edge,position=None):
        return self.add_module(kind,position=position,edge=edge)
    def remove_module(self,node):
        if node.permanent:return
        self.modules.remove(node);self.edges=[edge for edge in self.edges if node.key not in edge];self.scene().removeItem(node)
        if self.on_remove:self.on_remove(node.key)
        self.update_cables();self.fit_width()
    def reorder(self):
        # Geometry-only edits must not launch image processing.
        self.request_visual_update()
    def ordered_modules(self,require_output=True):
        from .wiring import ordered_ids
        by_id={node.key:node for node in self.modules}
        ordered,_=ordered_ids(by_id,self.edges,require_output)
        return [by_id[key] for key in ordered]
    def request_visual_update(self):
        # Do not mutate scene geometry from an itemChange callback.
        if hasattr(self,'_visual_timer') and not self._visual_timer.isActive():self._visual_timer.start(0)
    def flush_visual_update(self):
        self.update_cables();self.expand_scene()
    def update_cables(self):
        if not hasattr(self,'output'):return
        nodes={n.key:n for n in [self.input]+self.modules+[self.output]}
        previous={line.edge:line for line in self.cables};current=[]
        for edge in self.edges:
            if edge[0] not in nodes or edge[1] not in nodes:continue
            source,target=nodes[edge[0]],nodes[edge[1]]
            start=source.pos()+QPointF(135,76);end=target.pos()+QPointF(135,0)
            path=self.cable_path(start,end);gradient=QLinearGradient(start,end);gradient.setColorAt(0,QColor(source.accent));gradient.setColorAt(1,QColor(target.accent));pen=QPen(QBrush(gradient),2.6)
            line=previous.pop(edge,None)
            if line is None:line=Cable(self,edge,path,pen);self.scene().addItem(line)
            else:line.setPath(path);line.setPen(pen)
            current.append(line)
        for line in previous.values():self.scene().removeItem(line)
        self.cables=current
    def cable_path(self,start,end):
        bend=max(28,abs(end.y()-start.y())*.5);path=QPainterPath(start);path.cubicTo(start+QPointF(0,bend),end-QPointF(0,bend),end);return path
    def disconnect(self,edge):
        self.connection_error=''
        if edge in self.edges:self.edges.remove(edge)
        self.update_cables()
        if self.on_change:self.on_change()
    def begin_cable(self,port):
        self.drag_port=port;self.drag_line=self.scene().addPath(QPainterPath(),QPen(QColor('#91c4ff'),2,Qt.PenStyle.DashLine));self.drag_line.setZValue(4)
    def drag_cable(self,position):
        if self.drag_line is not None:self.drag_line.setPath(self.cable_path(self.drag_port.scenePos(),position))
    def end_cable(self,position):
        source=self.drag_port;target=next((item for item in self.scene().items(QRectF(position.x()-9,position.y()-9,18,18)) if isinstance(item,Port) and item is not source),None)
        if self.drag_line is not None:self.scene().removeItem(self.drag_line)
        self.drag_line=None;self.drag_port=None
        if target:self.connect_ports(source,target)
    def connect_ports(self,a,b):
        self.connection_error=''
        if a.direction==b.direction:self.connection_error='Connect an output port to an input port.'
        else:
            source,target=(a,b) if a.direction=='out' else (b,a);edge=(source.node.key,target.node.key)
            if edge in self.edges:return
            if edge[0]==edge[1]:self.connection_error='A module cannot connect to itself.'
            elif any(e[0]==edge[0] or e[1]==edge[1] for e in self.edges):self.connection_error='Port in use: disconnect the existing cable first.'
            else:
                links=dict(self.edges);current=edge[1];seen=set()
                while current in links and current not in seen:
                    seen.add(current);current=links[current]
                if current==edge[0]:self.connection_error='Cyclic connections are not allowed.'
                else:self.edges.append(edge)
        self.update_cables()
        if self.on_change:self.on_change()
    def drawBackground(self,painter,rect):
        paint_metal(painter,rect.united(self.sceneRect()),'well',0,False)
    def expand_scene(self):
        bounds=self.scene().itemsBoundingRect()
        if not self.sceneRect().contains(bounds):self.scene().setSceneRect(self.sceneRect().united(bounds.adjusted(-40,-40,40,40)))
    def fit_width(self):
        if self._fitting:return
        self._fitting=True
        try:
            from PyQt6.QtGui import QTransform
            scale=min(1.,max(.5,(self.viewport().width()-4)/440))
            if abs(self.transform().m11()-scale)>.002:self.setTransform(QTransform.fromScale(scale,scale))
            minimum=QRectF(0,0,440,max(650,self.viewport().height()/scale-2))
            self.scene().setSceneRect(self.sceneRect().united(minimum));self.expand_scene()
        finally:self._fitting=False
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'_resize_timer'):self._resize_timer.start(0)
    def module_menu(self,position,node=None):
        menu=QMenu(self)
        add=menu.addMenu('Add module')
        for kind,title in MODULE_CATALOG:
            action=add.addAction(title);action.triggered.connect(lambda checked=False,k=kind:self.add_module(k,position=self.mapToScene(self.viewport().mapFromGlobal(position))))
        if node is not None:
            menu.addSeparator();menu.addAction('Open controls',lambda:self.open_panel(node.key))
            if not node.permanent:
                menu.addAction('Remove module · Delete',lambda:self.remove_module(node))
        menu.exec(position)
    def node_at(self,position):
        item=self.itemAt(position)
        while item is not None and not isinstance(item,Node):item=item.parentItem()
        return item
    def keyPressEvent(self,event):
        selected=[node for node in self.modules if node.isSelected()]
        if event.key() in (Qt.Key.Key_Delete,Qt.Key.Key_Backspace):
            for cable in list(self.cables):
                if cable.isSelected():self.disconnect(cable.edge)
            for node in selected:self.remove_module(node)
            event.accept();return
        super().keyPressEvent(event)
    def contextMenuEvent(self,event):
        cable=next((item for item in self.items(event.pos()) if isinstance(item,Cable)),None)
        if cable:
            menu=QMenu(self);insert=menu.addMenu('Insert module here')
            edge=cable.edge;point=self.mapToScene(event.pos())
            for kind,title in MODULE_CATALOG:
                insert.addAction(title,lambda checked=False,k=kind,e=edge,p=point:self.insert_module(k,e,p))
            menu.addSeparator();menu.addAction('Disconnect cable',lambda:self.disconnect(edge));menu.exec(event.globalPos())
        else:self.module_menu(event.globalPos(),self.node_at(event.pos()))
    def mouseDoubleClickEvent(self,event):
        if isinstance(self.itemAt(event.pos()),(BypassButton,Port)):event.accept();return
        node=self.node_at(event.pos())
        if node is not None:self.open_panel(node.key)
        else:
            menu=QMenu(self)
            for kind,title in MODULE_CATALOG:
                action=menu.addAction(title);action.triggered.connect(lambda checked=False,k=kind:self.add_module(k,position=self.mapToScene(event.pos())))
            menu.exec(event.globalPosition().toPoint())
        event.accept()
