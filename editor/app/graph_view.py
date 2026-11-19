"""Сюжетный граф: узлы с выходами, рёбра, создание и связывание мышью, вход в главы.

Показывается один уровень вложенности: корень или содержимое одной главы. Рёбра, ведущие
за пределы уровня, рисуются как «→ куда», входящие снаружи — значком «вход» на узле.
"""
from __future__ import annotations

import math
from collections import defaultdict

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView, QMenu

from vnformat.expr import to_text

from . import graph_ops
from .document import ProjectDocument

W = 250
HEAD = 28
SUB = 24
ROW = 22
PORT_R = 6

TYPE_STYLE = {
    "scene": (QColor("#4f7cac"), "Сцена"),
    "branch": (QColor("#b8860b"), "Ветвление"),
    "ending": (QColor("#a8434b"), "Концовка"),
    "chapter": (QColor("#3d8b6d"), "Глава"),
}
ENDING_KIND = {"good": "хорошая", "bad": "плохая", "neutral": "нейтральная", "secret": "тайная"}
SEVERITY_COLOR = {"error": QColor("#d64545"), "warning": QColor("#e0a020")}


def _elide(text: str, font: QFont, width: float) -> str:
    return QFontMetricsF(font).elidedText(text, Qt.ElideRight, width)


# ---------------------------------------------------------------- элементы

class NodeItem(QGraphicsObject):
    def __init__(self, view: "GraphView", node: dict, exits: list[tuple[str, str]], subtitle: str,
                 is_start: bool, is_entry: bool, has_inbound_from_outside: bool):
        super().__init__()
        self.view, self.node, self.nid = view, node, node["id"]
        self.exits = exits                       # [(port, подпись)]
        self.subtitle = subtitle
        self.is_start, self.is_entry, self.inbound = is_start, is_entry, has_inbound_from_outside
        self.issues: list = []
        self.edges: list["EdgeItem"] = []
        self.height = HEAD + SUB + len(exits) * ROW + (8 if exits else 4)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        self.color, self.type_title = TYPE_STYLE.get(node.get("type"), (QColor("#777"), "?"))
        self.title_font = QFont()
        self.title_font.setBold(True)
        self.small_font = QFont()
        self.small_font.setPointSizeF(max(7.0, self.small_font.pointSizeF() - 1))

    def boundingRect(self):
        return QRectF(-4, -16, W + 8, self.height + 20)

    def shape(self):
        p = QPainterPath()
        p.addRect(QRectF(0, 0, W, self.height))
        return p

    def port_pos(self, port: str) -> QPointF:
        for i, (p, _label) in enumerate(self.exits):
            if p == port:
                return self.pos() + QPointF(W, HEAD + SUB + i * ROW + ROW / 2)
        return self.pos() + QPointF(W / 2, self.height)

    def port_at(self, local: QPointF) -> str | None:
        for i, (p, _label) in enumerate(self.exits):
            c = QPointF(W, HEAD + SUB + i * ROW + ROW / 2)
            if (local - c).manhattanLength() <= PORT_R * 2.2:
                return p
        return None

    def in_pos(self) -> QPointF:
        return self.pos() + QPointF(W / 2, 0)

    def paint(self, p: QPainter, opt, widget=None):
        lod = opt.levelOfDetailFromTransform(p.worldTransform())
        rect = QRectF(0, 0, W, self.height)
        selected = self.isSelected()
        key = self.node.get("importance") == "key"
        p.setPen(QPen(QColor("#f2b134") if selected else self.color.darker(130), 3 if selected else (2 if key else 1)))
        p.setBrush(QBrush(QColor("#fbfbfd")))
        p.drawRoundedRect(rect, 8, 8)
        head = QPainterPath()
        head.setFillRule(Qt.WindingFill)          # иначе пересечение двух фигур «вырезается»
        head.addRoundedRect(QRectF(0, 0, W, HEAD), 8, 8)
        head.addRect(QRectF(0, HEAD / 2, W, HEAD / 2))
        p.fillPath(head, self.color)
        if self.node.get("type") == "chapter":     # «стопка» — внутри есть содержимое
            p.setPen(QPen(self.color.darker(120), 1))
            p.drawLine(QPointF(6, self.height + 4), QPointF(W - 6, self.height + 4))
            p.drawLine(QPointF(12, self.height + 8), QPointF(W - 12, self.height + 8))
        if lod < 0.35:
            return
        p.setPen(QColor("white"))
        p.setFont(self.title_font)
        mark = "★ " if key else ""
        p.drawText(QRectF(10, 0, W - 20, HEAD), Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(mark + self.node.get("name", self.nid), self.title_font, W - 20))
        p.setFont(self.small_font)
        p.setPen(QColor("#555"))
        p.drawText(QRectF(10, HEAD, W - 20, SUB), Qt.AlignVCenter | Qt.AlignLeft,
                   _elide(self.subtitle, self.small_font, W - 20))
        for i, (_port, label) in enumerate(self.exits):
            y = HEAD + SUB + i * ROW
            p.setPen(QPen(QColor("#e4e4ea"), 1))
            p.drawLine(QPointF(8, y), QPointF(W - 8, y))
            p.setPen(QColor("#333"))
            p.drawText(QRectF(12, y, W - 30, ROW), Qt.AlignVCenter | Qt.AlignRight,
                       _elide(label, self.small_font, W - 40))
            connected = any(e.port == _port for e in self.edges if e.src is self)
            p.setPen(QPen(self.color.darker(140), 1.5))
            p.setBrush(self.color if connected else QColor("white"))
            p.drawEllipse(QPointF(W, y + ROW / 2), PORT_R, PORT_R)
        badges = []
        if self.is_start:
            badges.append(("СТАРТ", QColor("#2e7d32")))
        elif self.is_entry:
            badges.append(("начало главы", QColor("#3d8b6d")))
        if self.inbound and not self.is_entry and not self.is_start:
            badges.append(("вход извне", QColor("#607d8b")))
        x = 0.0
        p.setFont(self.small_font)
        fm = QFontMetricsF(self.small_font)
        for text, col in badges:
            w = fm.horizontalAdvance(text) + 10
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, -15, w, 13), 4, 4)
            p.setPen(QColor("white"))
            p.drawText(QRectF(x, -15, w, 13), Qt.AlignCenter, text)
            x += w + 4
        if self.issues:
            sev = "error" if any(i.severity == "error" for i in self.issues) else "warning"
            p.setPen(Qt.NoPen)
            p.setBrush(SEVERITY_COLOR[sev])
            p.drawEllipse(QPointF(W - 12, -8), 7, 7)
            p.setPen(QColor("white"))
            p.drawText(QRectF(W - 19, -15, 14, 14), Qt.AlignCenter, "!")

    def set_issues(self, issues):
        self.issues = issues
        self.setToolTip("\n".join(f"• {i.message}" for i in issues) if issues else "")
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            for e in self.edges:
                e.update_path()
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, ev):
        # отложенно: вход в главу пересоздаёт сцену, а этот элемент ещё обрабатывает событие
        QTimer.singleShot(0, lambda nid=self.nid, v=self.view: v.node_activated.emit(nid))

    def mousePressEvent(self, ev):
        port = self.port_at(ev.pos()) if ev.button() == Qt.LeftButton else None
        if port is not None:
            self.view.begin_link(self, port)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def hoverMoveEvent(self, ev):
        self.setCursor(Qt.CrossCursor if self.port_at(ev.pos()) else Qt.ArrowCursor)


class EdgeItem(QGraphicsItem):
    """Ребро. dst=None — ведёт за пределы уровня (подпись target_label)."""

    def __init__(self, src: NodeItem, port: str, dst: NodeItem | None, edge_ids: list[str],
                 target_label: str = "", aggregated: bool = False):
        super().__init__()
        self.src, self.port, self.dst = src, port, dst
        self.edge_ids, self.target_label, self.aggregated = edge_ids, target_label, aggregated
        self.setZValue(0)
        self.setFlag(QGraphicsItem.ItemIsSelectable, not aggregated)
        self._path = QPainterPath()
        src.edges.append(self)
        if dst:
            dst.edges.append(self)
        self.update_path()

    def update_path(self):
        """Из выхода справа — вниз вдоль края узла, под узлом — к верху цели. Так ребро не уходит под узлы."""
        a = self.src.port_pos(self.port)
        ports = [p for p, _ in self.src.exits]
        path = QPainterPath(a)
        if self.port in ports:
            idx = ports.index(self.port)
            x1 = self.src.pos().x() + W + 16 + 7 * idx
            y1 = self.src.pos().y() + self.src.height + 14 + 5 * idx
            path.lineTo(x1 - 8, a.y())
            path.quadTo(QPointF(x1, a.y()), QPointF(x1, a.y() + 8))
            path.lineTo(x1, y1 - 8)
            start = QPointF(x1, y1 - 8)
        else:
            start = a
        b = self.dst.in_pos() if self.dst is not None else start + QPointF(50, 60)
        dy = max(40.0, (b.y() - start.y()) * 0.5)
        path.cubicTo(start + QPointF(0, dy), b - QPointF(0, dy), b)
        self.prepareGeometryChange()
        self._path = path
        self._bounds = path.boundingRect().adjusted(-8, -8, 8 + (220 if self.dst is None else 0), 22)

    def boundingRect(self):
        return self._bounds

    def shape(self):
        from PySide6.QtGui import QPainterPathStroker
        s = QPainterPathStroker()
        s.setWidth(10)
        return s.createStroke(self._path)

    def paint(self, p: QPainter, opt, widget=None):
        col = QColor("#f2b134") if self.isSelected() else QColor("#7d8590")
        pen = QPen(col, 2.2 if self.isSelected() else 1.6)
        if self.aggregated or self.dst is None:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(self._path)
        end = self._path.currentPosition()
        d = end - self._path.pointAtPercent(0.97)
        angle = math.atan2(d.y(), d.x())
        p.setBrush(col)
        p.setPen(Qt.NoPen)
        tip = [end, end - QPointF(math.cos(angle - 0.4) * 10, math.sin(angle - 0.4) * 10),
               end - QPointF(math.cos(angle + 0.4) * 10, math.sin(angle + 0.4) * 10)]
        p.drawPolygon(tip)
        if self.dst is None and self.target_label:
            p.setPen(QColor("#555"))
            p.drawText(QRectF(end.x() + 6, end.y() - 4, 200, 18), Qt.AlignLeft | Qt.AlignVCenter, "→ " + self.target_label)


# ---------------------------------------------------------------- вид

class GraphView(QGraphicsView):
    selection_changed = Signal(list)          # ID выбранных узлов
    node_activated = Signal(str)              # двойной клик
    container_changed = Signal(object)        # ID главы или None

    def __init__(self, doc: ProjectDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.container: str | None = None
        self.items: dict[str, NodeItem] = {}
        self._link = None                     # (NodeItem, port, QGraphicsPathItem)
        self._press_pos: dict[str, QPointF] = {}
        self.setScene(QGraphicsScene(self))
        self.scene().setSceneRect(-5000, -5000, 10000, 10000)
        self.scene().selectionChanged.connect(self._selection)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setOptimizationFlags(QGraphicsView.DontAdjustForAntialiasing)
        self.setBackgroundBrush(QColor("#eef0f4"))
        self._rest = QTimer(self, singleShot=True, interval=150)     # сглаживание только в покое
        self._rest.timeout.connect(lambda: (self.setRenderHint(QPainter.Antialiasing, True), self.viewport().update()))
        for bar in (self.horizontalScrollBar(), self.verticalScrollBar()):
            bar.valueChanged.connect(self._moving)
        doc.changed.connect(lambda _keys: self.rebuild())
        doc.reloaded.connect(lambda: self.enter(None))
        doc.issues_changed.connect(self._apply_issues)

    # ----------------------------------------------------------- построение
    def enter(self, container: str | None):
        self.container = container
        self.rebuild()
        self.fit()
        self.container_changed.emit(container)

    def _rep(self, nid: str, nodes: dict) -> str | None:
        """Представитель узла на текущем уровне: он сам или его глава-предок на этом уровне."""
        cur, guard = nid, 0
        while cur in nodes and guard < 64:
            if nodes[cur].get("parent") == self.container:
                return cur
            cur = nodes[cur].get("parent")
            guard += 1
        return None

    def rebuild(self):
        selected = {i.nid for i in self.scene().selectedItems() if isinstance(i, NodeItem)}
        self.scene().blockSignals(True)
        self.scene().clear()
        self.items.clear()
        doc = self.doc
        nodes = {n["id"]: n for n in doc.nodes()}
        if self.container is not None and self.container not in nodes:
            self.container = None
        start = (doc.get("project") or {}).get("start")
        entry = nodes.get(self.container, {}).get("entry") if self.container else None
        level = [n for n in nodes.values() if n.get("parent") == self.container]
        edges = doc.edges()
        inbound_outside = {e["to"] for e in edges if self._rep(e["from"]["node"], nodes) is None}

        missing = [n["id"] for n in level if doc.position(n["id"]) is None]
        auto = auto_layout(level, edges, nodes, self) if missing else {}
        for n in level:
            item = NodeItem(self, n, self._exits(n), self._subtitle(n, nodes),
                            is_start=n["id"] == start or (start in nodes and self._rep(start, nodes) == n["id"]
                                                          and n["type"] == "chapter"),
                            is_entry=n["id"] == entry, has_inbound_from_outside=n["id"] in inbound_outside)
            x, y = doc.position(n["id"]) or auto.get(n["id"], (0, 0))
            item.setPos(x, y)
            self.scene().addItem(item)
            self.items[n["id"]] = item

        for e in edges:
            src, dst = e["from"]["node"], e["to"]
            rs, rd = self._rep(src, nodes), self._rep(dst, nodes)
            if rs is None or rs not in self.items or (rs != src and rd == rs):
                continue                         # снаружи уровня или внутри одной главы — не рисуем
            port = e["from"]["port"] if rs == src else f"{src}|{e['from']['port']}"   # выход узла внутри главы
            if rd is not None and rd in self.items:
                self.scene().addItem(EdgeItem(self.items[rs], port, self.items[rd], [e["id"]]))
            else:
                self.scene().addItem(EdgeItem(self.items[rs], port, None, [e["id"]],
                                              target_label=self._where(dst, nodes)))

        for nid in selected & set(self.items):
            self.items[nid].setSelected(True)
        self.scene().blockSignals(False)
        self._apply_issues(doc.issues)
        self._selection()

    def _where(self, nid: str, nodes: dict) -> str:
        n = nodes.get(nid, {})
        parent = nodes.get(n.get("parent"), {})
        return f"{parent.get('name')} / {n.get('name', nid)}" if parent else n.get("name", nid)

    def _exit_label(self, ex, vars_: dict) -> str:
        if ex.kind == "choice":
            return self.doc.text(ex.text_key) or ex.port
        if ex.kind == "next":
            return "дальше"
        if ex.kind == "else":
            return "иначе"
        if ex.kind == "case":
            return ex.label or to_text(ex.condition, vars_)
        return f"переход {ex.port}"

    def _exits(self, n: dict) -> list[tuple[str, str]]:
        vars_ = {v["id"]: v["name"] for v in (self.doc.get("variables") or {}).get("variables", [])}
        if n.get("type") != "chapter":
            return [(ex.port, self._exit_label(ex, vars_)) for ex in self.doc.exits(n)]
        # У главы — выходы её узлов, которые никуда не ведут или ведут за пределы главы:
        # отсюда главы связываются между собой прямо на верхнем уровне.
        nodes = {m["id"]: m for m in self.doc.nodes()}
        inside = set()
        frontier = {n["id"]}
        while frontier:
            frontier = {m for m, d in nodes.items() if d.get("parent") in frontier} - inside
            inside |= frontier
        target = {(e["from"]["node"], e["from"]["port"]): e["to"] for e in self.doc.edges()}
        out = []
        for mid in sorted(inside, key=lambda i: (nodes[i].get("type") == "ending", nodes[i].get("name", ""))):
            m = nodes[mid]
            if m.get("type") == "chapter":
                continue
            for ex in self.doc.exits(m):
                dst = target.get((mid, ex.port))
                if dst is None or dst not in inside:
                    out.append((f"{mid}|{ex.port}", f"{m.get('name', mid)}: {self._exit_label(ex, vars_)}"))
        return out

    def _subtitle(self, n: dict, nodes: dict) -> str:
        t = n.get("type")
        if t == "scene":
            scene = self.doc.scenes().get(n.get("scene"), {})
            cmds = scene.get("commands", [])
            first = next((self.doc.text(c.get("text")) for c in cmds if c.get("cmd") in ("say", "narrate")), "")
            lines = sum(1 for c in cmds if c.get("cmd") in ("say", "narrate"))
            return f"{lines} реп. · {first}" if first else "пустая сцена"
        if t == "branch":
            return f"условий: {len(n.get('cases', []))} + иначе"
        if t == "ending":
            e = n.get("ending", {})
            return f"{ENDING_KIND.get(e.get('kind'), '')}: {self.doc.text(e.get('title'))}"
        if t == "chapter":
            inside = sum(1 for m in nodes.values() if m.get("parent") == n["id"])
            return f"узлов внутри: {inside} · двойной клик — открыть"
        return ""

    def _apply_issues(self, issues):
        by_node = defaultdict(list)
        allnodes = {n["id"]: n for n in self.doc.nodes()}
        for i in issues:
            if i.severity not in ("error", "warning"):
                continue
            for t in issue_nodes(self.doc, i):
                rep = self._rep(t, allnodes) if t in allnodes else None
                if rep:
                    by_node[rep].append(i)
        for nid, item in self.items.items():
            item.set_issues(by_node.get(nid, []))

    # ----------------------------------------------------------- выделение и движение
    def _selection(self):
        try:
            sel = [i.nid for i in self.scene().selectedItems() if isinstance(i, NodeItem)]
        except RuntimeError:
            return
        self.selection_changed.emit(sel)

    def select(self, nid: str):
        nodes = {n["id"]: n for n in self.doc.nodes()}
        if nid not in nodes:
            return
        parent = nodes[nid].get("parent")
        if self._rep(nid, nodes) != nid:
            self.enter(parent)
        self.scene().clearSelection()
        if nid in self.items:
            self.items[nid].setSelected(True)
            self.centerOn(self.items[nid])

    def _moving(self, *_):
        if self.renderHints() & QPainter.Antialiasing:
            self.setRenderHint(QPainter.Antialiasing, False)
        self._rest.start()

    def fit(self):
        rect = self.scene().itemsBoundingRect()
        if rect.isNull():
            self.resetTransform()
            self.centerOn(0, 0)
            return
        self.fitInView(rect.adjusted(-80, -60, 80, 60), Qt.KeepAspectRatio)
        if self.transform().m11() > 1.0:
            self.resetTransform()
            self.centerOn(rect.center())

    def wheelEvent(self, ev):
        self._moving()
        f = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        z = self.transform().m11() * f
        if 0.1 <= z <= 2.5:
            self.scale(f, f)

    def mousePressEvent(self, ev):
        if ev.button() in (Qt.MiddleButton, Qt.RightButton) and ev.modifiers() & Qt.AltModifier or ev.button() == Qt.MiddleButton:
            self._pan = ev.position()                       # панорама средней кнопкой
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(ev)
        self._press_pos = {nid: it.pos() for nid, it in self.items.items() if it.isSelected()}

    def mouseMoveEvent(self, ev):
        if getattr(self, "_pan", None) is not None:
            delta = ev.position() - self._pan
            self._pan = ev.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            return
        if self._link:
            self._moving()
            src, port, line = self._link
            a = src.port_pos(port)
            b = self.mapToScene(ev.position().toPoint())
            path = QPainterPath(a)
            path.cubicTo(a + QPointF(60, 0), b - QPointF(0, 60), b)
            line.setPath(path)
            return
        if ev.buttons() & Qt.LeftButton and self._press_pos:
            self._moving()
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if getattr(self, "_pan", None) is not None:
            self._pan = None
            self.viewport().unsetCursor()
            return
        if self._link:
            self._finish_link(ev)
            return
        super().mouseReleaseEvent(ev)
        moved = {nid: (it.pos().x(), it.pos().y()) for nid, it in self.items.items()
                 if nid in self._press_pos and it.pos() != self._press_pos[nid]}
        self._press_pos = {}
        if moved:
            graph_ops.move_nodes(self.doc, moved)

    # ----------------------------------------------------------- связывание
    def begin_link(self, src: NodeItem, port: str):
        from PySide6.QtWidgets import QGraphicsPathItem
        line = QGraphicsPathItem()
        pen = QPen(QColor("#f2b134"), 2, Qt.DashLine)
        line.setPen(pen)
        line.setZValue(10)
        self.scene().addItem(line)
        self._link = (src, port, line)

    def _finish_link(self, ev):
        src, port, line = self._link
        self._link = None
        self.scene().removeItem(line)
        pos = self.mapToScene(ev.position().toPoint())
        target = next((i for i in self.scene().items(pos) if isinstance(i, NodeItem)), None)
        if target is not None and target is not src:
            graph_ops.connect(self.doc, src.nid, port, target.nid)
        elif target is None:
            self._create_menu(pos, ev.globalPosition().toPoint(), link=(src.nid, port))

    # ----------------------------------------------------------- меню и клавиши
    def contextMenuEvent(self, ev):
        pos = self.mapToScene(ev.pos())
        item = next((i for i in self.scene().items(pos) if isinstance(i, (NodeItem, EdgeItem))), None)
        if isinstance(item, NodeItem):
            if not item.isSelected():
                self.scene().clearSelection()
                item.setSelected(True)
            m = QMenu(self)
            n = item.node
            if n.get("type") == "chapter":
                m.addAction("Открыть главу", lambda: self.enter(n["id"]))
            if n.get("parent"):
                m.addAction("Сделать первым узлом главы", lambda: graph_ops.set_chapter_entry(self.doc, n["id"]))
            m.addAction("Начинать игру отсюда", lambda: graph_ops.set_start(self.doc, n["id"]))
            imp = "Снять отметку «ключевой»" if n.get("importance") == "key" else "Отметить как ключевой"
            m.addAction(imp, lambda: graph_ops.update_node(
                self.doc, n["id"], imp, importance=None if n.get("importance") == "key" else "key"))
            m.addSeparator()
            m.addAction("Копировать\tCtrl+C", self.copy_selected)
            m.addAction("Дублировать\tCtrl+D", self.duplicate_selected)
            m.addAction("Удалить\tDel", self.delete_selected)
            m.exec(ev.globalPos())
        elif isinstance(item, EdgeItem) and not item.aggregated:
            m = QMenu(self)
            m.addAction("Удалить связь", lambda: graph_ops.disconnect(self.doc, set(item.edge_ids)))
            m.exec(ev.globalPos())
        else:
            self._create_menu(pos, ev.globalPos())

    def _create_menu(self, pos: QPointF, global_pos, link=None):
        m = QMenu(self)
        for kind in ("scene", "branch", "ending", "chapter"):
            act = QAction(f"Новая {graph_ops.NODE_TITLES[kind].lower()}" if kind != "ending" else "Новая концовка", m)
            if kind in ("scene", "chapter"):
                act.setText(f"Новая {graph_ops.NODE_TITLES[kind].lower()}")
            if kind == "branch":
                act.setText("Новое ветвление")
            act.triggered.connect(lambda _=False, k=kind: self.create_node(k, pos, link))
            m.addAction(act)
        if link:
            self._cross_menu(m, link)
        else:
            from PySide6.QtWidgets import QApplication
            mime = QApplication.clipboard().mimeData()
            paste = m.addAction("Вставить\tCtrl+V", lambda: self.paste(pos))
            paste.setEnabled(bool(mime and mime.hasFormat(graph_ops.CLIP_MIME)))
        m.exec(global_pos)

    def _cross_menu(self, m: QMenu, link):
        """Связать выход с узлом в другой главе: меню «Глава → её узлы»."""
        nodes = {n["id"]: n for n in self.doc.nodes()}
        chapters = [n for n in nodes.values() if n.get("type") == "chapter" and n["id"] != self.container]
        if not chapters and self.container is None:
            return
        sub = m.addMenu("Связать с узлом в другой главе")
        for ch in sorted(chapters, key=lambda c: c.get("name", "")):
            cm = sub.addMenu(ch.get("name", ch["id"]))
            cm.addAction("▶ Начало главы", lambda c=ch["id"]: graph_ops.connect(self.doc, link[0], link[1], c))
            cm.addSeparator()
            for n in sorted((x for x in nodes.values() if x.get("parent") == ch["id"] and x.get("type") != "chapter"),
                            key=lambda x: x.get("name", "")):
                cm.addAction(n.get("name", n["id"]), lambda t=n["id"]: graph_ops.connect(self.doc, link[0], link[1], t))
        top = [n for n in nodes.values() if n.get("parent") is None and n.get("type") != "chapter"]
        if top and self.container is not None:
            tm = sub.addMenu("Вне глав")
            for n in top:
                tm.addAction(n.get("name", n["id"]), lambda t=n["id"]: graph_ops.connect(self.doc, link[0], link[1], t))

    def create_node(self, kind: str, pos: QPointF, link=None) -> str:
        nid = graph_ops.add_node(self.doc, kind, self.container, pos.x() - W / 2, pos.y())
        if link:
            graph_ops.connect(self.doc, link[0], link[1], nid)
        self.select(nid)
        return nid

    def delete_selected(self):
        nodes = {i.nid for i in self.scene().selectedItems() if isinstance(i, NodeItem)}
        edges = {eid for i in self.scene().selectedItems() if isinstance(i, EdgeItem) and not i.aggregated
                 for eid in i.edge_ids}
        if nodes:
            graph_ops.delete_nodes(self.doc, nodes)
        elif edges:
            graph_ops.disconnect(self.doc, edges)

    def copy_selected(self) -> bool:
        import json
        from PySide6.QtCore import QMimeData
        from PySide6.QtWidgets import QApplication
        ids = {i.nid for i in self.scene().selectedItems() if isinstance(i, NodeItem)}
        payload = graph_ops.copy_nodes(self.doc, ids)
        if not payload:
            return False
        mime = QMimeData()
        data = json.dumps(payload, ensure_ascii=False)
        mime.setData(graph_ops.CLIP_MIME, data.encode("utf-8"))
        mime.setText(data)
        QApplication.clipboard().setMimeData(mime)
        return True

    def paste(self, at: QPointF | None = None) -> list[str]:
        import json
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QApplication
        mime = QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat(graph_ops.CLIP_MIME):
            return []
        payload = json.loads(bytes(mime.data(graph_ops.CLIP_MIME)).decode("utf-8"))
        if at is None:
            local = self.viewport().mapFromGlobal(QCursor.pos())
            at = self.mapToScene(local) if self.viewport().rect().contains(local) else \
                self.mapToScene(self.viewport().rect().center())
        new = graph_ops.paste_nodes(self.doc, payload, self.container, at.x(), at.y())
        self.scene().clearSelection()
        for nid in new:
            if nid in self.items:
                self.items[nid].setSelected(True)
        return new

    def duplicate_selected(self):
        sel = [i for i in self.scene().selectedItems() if isinstance(i, NodeItem)]
        if sel and self.copy_selected():
            x = min(i.pos().x() for i in sel) + 40
            y = min(i.pos().y() for i in sel) + 40
            self.paste(QPointF(x, y))

    def keyPressEvent(self, ev):
        if ev.matches(QKeySequence.Copy):
            self.copy_selected()
        elif ev.matches(QKeySequence.Paste):
            self.paste()
        elif ev.key() == Qt.Key_D and ev.modifiers() & Qt.ControlModifier:
            self.duplicate_selected()
        elif ev.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected()
        elif ev.key() == Qt.Key_F:
            self.fit()
        else:
            super().keyPressEvent(ev)

    def arrange(self):
        """Авто-раскладка текущего уровня — одна отменяемая правка."""
        nodes = {n["id"]: n for n in self.doc.nodes()}
        level = [n for n in nodes.values() if n.get("parent") == self.container]
        pos = auto_layout(level, self.doc.edges(), nodes, self)
        graph_ops.move_nodes(self.doc, pos)
        self.fit()


def issue_nodes(doc: ProjectDocument, issue) -> list[str]:
    """Узлы графа, к которым относится проблема (по пути к полю или по файлу сцены)."""
    graph = doc.get("graph") or {}
    if issue.file.endswith("graph.json") and issue.path.startswith(("nodes[", "edges[")):
        kind = "nodes" if issue.path.startswith("nodes[") else "edges"
        idx = int(issue.path[6:issue.path.index("]")])
        items = graph.get(kind, [])
        if idx < len(items) and isinstance(items[idx], dict):
            return [items[idx].get("id") if kind == "nodes" else items[idx].get("from", {}).get("node")]
        return []
    if "/scenes/" in issue.file:
        sid = issue.file.rsplit("/", 1)[-1][:-5]
        return [n["id"] for n in doc.nodes() if n.get("type") == "scene" and n.get("scene") == sid]
    if issue.file.endswith("graph.json") and issue.where.startswith("узел "):
        return [issue.where.split()[1]]
    return []


def auto_layout(level: list[dict], edges: list[dict], nodes: dict, view: GraphView) -> dict[str, tuple[float, float]]:
    """Слои сверху вниз по самому длинному пути от входа; порядок в слое — по среднему положению родителей."""
    ids = [n["id"] for n in level]
    idset = set(ids)
    succ = defaultdict(list)
    for e in edges:
        s, d = view._rep(e["from"]["node"], nodes), view._rep(e["to"], nodes)
        if s in idset and d in idset and s != d:
            succ[s].append(d)
    indeg = {i: 0 for i in ids}
    for s in succ:
        for d in succ[s]:
            indeg[d] += 1
    entry = nodes.get(view.container, {}).get("entry") if view.container else (
        view._rep((view.doc.get("project") or {}).get("start", ""), nodes))
    roots = [entry] if entry in idset else [i for i in ids if indeg[i] == 0] or ids[:1]
    layer = {}
    # длинейший путь по DAG; обратные рёбра (циклы) игнорируются через ограничение глубины
    stack = [(r, 0, frozenset()) for r in roots]
    while stack:
        nid, depth, path = stack.pop()
        if nid in path or depth > len(ids):
            continue
        if depth > layer.get(nid, -1):
            layer[nid] = depth
            for d in succ[nid]:
                stack.append((d, depth + 1, path | {nid}))
    top = max(layer.values(), default=-1) + 1
    for i in ids:
        if i not in layer:
            layer[i] = top
    bottom = max(layer.values(), default=0)
    for i in ids:                              # концовки — нижним рядом, как в схеме Detroit
        if nodes[i].get("type") == "ending":
            layer[i] = max(bottom, 1)
    rows = defaultdict(list)
    for i in ids:
        rows[layer[i]].append(i)
    xpos: dict[str, float] = {}
    out: dict[str, tuple[float, float]] = {}
    y = 0.0
    preds = defaultdict(list)
    for s in succ:
        for d in succ[s]:
            preds[d].append(s)
    for depth in sorted(rows):
        row = rows[depth]
        row.sort(key=lambda i: (sum(xpos.get(p, 0) for p in preds[i]) / len(preds[i])) if preds[i] else ids.index(i))
        gap = W + 70
        x0 = -(len(row) - 1) * gap / 2
        tallest = 0
        for k, nid in enumerate(row):
            xpos[nid] = x0 + k * gap
            out[nid] = (x0 + k * gap, y)
            n = nodes[nid]
            tallest = max(tallest, HEAD + SUB + len(view.doc.exits(n)) * ROW + 8)
        y += tallest + 90
    return out
