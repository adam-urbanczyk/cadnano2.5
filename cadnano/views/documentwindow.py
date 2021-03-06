# -*- coding: utf-8 -*-
from collections import namedtuple

from PyQt5.QtCore import (
    Qt,
    QSettings,
    QPoint,
    QSize,
    QEvent
)
from PyQt5.QtGui import (
    QMoveEvent,
    QResizeEvent
)
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QWidget,
    QGraphicsItem,
    QMainWindow,
    QGraphicsScene
)


from cadnano import app
from cadnano.fileio.v3encode import reEmitPart
from cadnano.proxies.cnproxy import UndoStack
from cadnano.gui.mainwindow import ui_mainwindow
from cadnano.proxies.cnenum import (
    OrthoViewEnum,
    ViewReceiveEnum,
    ViewSendEnum,
    EnumType
)
from cadnano.views.gridview.gridrootitem import GridRootItem
from cadnano.views.gridview.tools.gridtoolmanager import GridToolManager
from cadnano.views.pathview.colorpanel import ColorPanel
from cadnano.views.pathview.pathrootitem import PathRootItem
from cadnano.views.pathview.tools.pathtoolmanager import PathToolManager
from cadnano.views.sliceview.slicerootitem import SliceRootItem
from cadnano.views.sliceview.tools.slicetoolmanager import SliceToolManager
from cadnano.views.abstractitems import AbstractTool
from cadnano.cntypes import (
    DocT,
    DocCtrlT,
    GraphicsViewT
)

# from PyQt5.QtOpenGL import QGLWidget
# # check out https://github.com/baoboa/pyqt5/tree/master/examples/opengl
# # for an example of the QOpenGlWidget added in Qt 5.4

class DocumentWindow(QMainWindow, ui_mainwindow.Ui_MainWindow):
    """:class`DocumentWindow` subclasses :class`QMainWindow` and
    :class`Ui_MainWindow`. It performs some initialization operations that
    must be done in code rather than using Qt Creator.

    Attributes:
        controller: DocumentController
    """

    def __init__(self, doc_ctrlr: DocCtrlT, parent=None):
        super(DocumentWindow, self).__init__(parent)

        self.controller = doc_ctrlr
        doc = doc_ctrlr.document()
        self.setupUi(self)
        self.settings = QSettings("cadnano.org", "cadnano2.5")
        # Appearance pref
        if not app().prefs.show_icon_labels:
            self.main_toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)

        # Outliner & PropertyEditor setup
        self.outliner_widget.configure(window=self, document=doc)
        self.property_widget.configure(window=self, document=doc)
        self.property_buttonbox.setVisible(False)

        self.tool_managers = None  # initialize

        self.views = {}
        self.views[ViewSendEnum.SLICE] = self._initSliceview(doc)
        self.views[ViewSendEnum.GRID]  = self._initGridview(doc)
        self.views[ViewSendEnum.PATH]  = self._initPathview(doc)

        self._initPathviewToolbar()
        self._initEditMenu()

        self.path_dock_widget.setTitleBarWidget(QWidget())
        self.grid_dock_widget.setTitleBarWidget(QWidget())
        self.slice_dock_widget.setTitleBarWidget(QWidget())
        self.inspector_dock_widget.setTitleBarWidget(QWidget())

        self.setCentralWidget(None)
        if app().prefs.orthoview_style_idx == OrthoViewEnum.SLICE:
            self.splitDockWidget(self.slice_dock_widget, self.path_dock_widget, Qt.Horizontal)
        elif app().prefs.orthoview_style_idx == OrthoViewEnum.GRID:
            self.splitDockWidget(self.grid_dock_widget, self.path_dock_widget, Qt.Horizontal)
        self._restoreGeometryandState()
        self._finishInit()

        doc.setViewNames(['slice', 'path', 'inspector'])
    # end def

    def document(self) -> DocT:
        return self.controller.document()

    def destroyWin(self):
        '''Save window state and destroy the tool managers.  Also destroy
        :class`DocumentController` object
        '''
        self.settings.beginGroup("MainWindow")
        # Saves the current state of this mainwindow's toolbars and dockwidgets
        self.settings.setValue("windowState", self.saveState())
        self.settings.endGroup()
        for mgr in self.tool_managers:
            mgr.destroyItem()
        self.controller = None

    ### ACCESSORS ###
    def undoStack(self) -> UndoStack:
        return self.controller.undoStack()

    def activateSelection(self, is_active: bool):
        self.path_graphics_view.activateSelection(is_active)
        self.slice_graphics_view.activateSelection(is_active)
        self.grid_graphics_view.activateSelection(is_active)

    ### EVENT HANDLERS ###
    def focusInEvent(self):
        """Handle an OS focus change into cadnano."""
        app().undoGroup.setActiveStack(self.controller.undoStack())

    def moveEvent(self, event: QMoveEvent):
        """Handle the moving of the cadnano window itself.

        Reimplemented to save state on move.
        """
        self.settings.beginGroup("MainWindow")
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("pos", self.pos())
        self.settings.endGroup()

    def resizeEvent(self, event: QResizeEvent):
        """Handle the resizing of the cadnano window itself.

        Reimplemented to save state on resize.
        """
        self.settings.beginGroup("MainWindow")
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("size", self.size())
        self.settings.endGroup()
        QWidget.resizeEvent(self, event)

    def changeEvent(self, event: QEvent):
        QWidget.changeEvent(self, event)

    # end def

    ### DRAWING RELATED ###

    ### PRIVATE HELPER METHODS ###
    def _restoreGeometryandState(self):
        settings = self.settings
        settings.beginGroup("MainWindow")
        geometry = settings.value("geometry")
        if geometry is not None:
            result = self.restoreGeometry(geometry)
            if result is False:
                print("MainWindow.restoreGeometry() failed.")
        else:
            print("Setting default MainWindow size: 1100x800")
            self.resize(settings.value("size", QSize(1100, 800)))
            self.move(settings.value("pos", QPoint(200, 200)))
            self.inspector_dock_widget.close()
            self.action_inspector.setChecked(False)

        # Restore the current state of this mainwindow's toolbars and dockwidgets
        window_state = settings.value("windowState")
        if window_state is not None:
            result = self.restoreState(window_state)
            if result is False:
                print("MainWindow.restoreState() failed.")
        settings.endGroup()
    # end def

    def destroyView(self, view_type: EnumType):
        '''
        Args:
            view_type: the name of the view

        Raises:
            ValueError for :obj:`view_type` not existing
        '''
        cnview = self.views.get(view_type)
        if cnview is not None:
            root_item = cnview.rootItem()
            root_item.destroyViewItems()
        else:
            raise ValueError("view_type: %s does not exist" % (view_type))

    def rebuildView(self, view_type: EnumType):
        '''Rebuild views which match view_type ORed argument.
        Only allows SLICE or GRID view to be active.  Not both at the same time

        Args:
            view_type: one or more O
        '''
        doc = self.document()

        # turn OFF all but the views we care about
        doc.changeViewSignaling(view_type)

        delta = 0
        if view_type & ViewSendEnum.SLICE:
            delta = ViewSendEnum.GRID
            self.destroyView(delta)
        elif view_type & ViewSendEnum.GRID:
            delta = ViewSendEnum.GRID
            self.destroyView(delta)

        for part in doc.getParts():
            reEmitPart(part)

        # turn ON all but the views we care about
        doc.changeViewSignaling(ViewSendEnum.ALL - delta)
    # end def

    def _initGridview(self, doc: DocT) -> GraphicsViewT:
        """Initializes Grid View.

        Args:
            doc: The :class:`Document` corresponding to the design

        Returns:
            :class:`CustomQGraphicsView`
        """
        grid_scene = QGraphicsScene(parent=self.grid_graphics_view)
        grid_root = GridRootItem(   rect=grid_scene.sceneRect(),
                                    parent=None,
                                    window=self,
                                    document=doc)
        grid_scene.addItem(grid_root)
        grid_scene.setItemIndexMethod(QGraphicsScene.NoIndex)
        assert grid_root.scene() == grid_scene
        ggv = self.grid_graphics_view
        ggv.setScene(grid_scene)
        ggv.scene_root_item = grid_root
        ggv.setName("GridView")
        self.grid_tool_manager = GridToolManager(self, grid_root)
        return ggv
    # end def

    def _initPathview(self, doc: DocT) -> GraphicsViewT:
        """Initializes Path View.

        Args:
            doc: The :class:`Document` corresponding to the design

        Returns:
            :class:`CustomQGraphicsView`
        """
        path_scene = QGraphicsScene(parent=self.path_graphics_view)
        path_root = PathRootItem(   rect=path_scene.sceneRect(),
                                    parent=None,
                                    window=self,
                                    document=doc)
        path_scene.addItem(path_root)
        path_scene.setItemIndexMethod(QGraphicsScene.NoIndex)
        assert path_root.scene() == path_scene
        pgv = self.path_graphics_view
        pgv.setScene(path_scene)
        pgv.scene_root_item = path_root
        pgv.setScaleFitFactor(0.7)
        pgv.setName("PathView")
        return pgv
    # end def

    def _initPathviewToolbar(self):
        """Initializes Path View Toolbar.
        """
        self.path_color_panel = ColorPanel()
        self.path_graphics_view.toolbar = self.path_color_panel  # HACK for customqgraphicsview
        path_view = self.views[ViewSendEnum.PATH]
        path_scene = path_view.cnScene()
        path_scene.addItem(self.path_color_panel)
        self.path_tool_manager = PathToolManager(self, path_view.rootItem())

        self.slice_tool_manager.path_tool_manager = self.path_tool_manager
        self.path_tool_manager.slice_tool_manager = self.slice_tool_manager

        self.grid_tool_manager.path_tool_manager = self.path_tool_manager
        self.path_tool_manager.grid_tool_manager = self.grid_tool_manager

        self.tool_managers = (self.path_tool_manager, self.slice_tool_manager, self.grid_tool_manager)

        self.insertToolBarBreak(self.main_toolbar)

        self.path_graphics_view.setupGL()
        self.slice_graphics_view.setupGL()
        self.grid_graphics_view.setupGL()
    # end def

    def _initSliceview(self, doc: DocT) -> GraphicsViewT:
        """Initializes Slice View.

        Args:
            doc: The :class:`Document` corresponding to the design

        Returns:
            :class:`CustomQGraphicsView`
        """
        slice_scene = QGraphicsScene(parent=self.slice_graphics_view)
        slice_root = SliceRootItem( rect=slice_scene.sceneRect(),
                                    parent=None,
                                    window=self,
                                    document=doc)
        slice_scene.addItem(slice_root)
        slice_scene.setItemIndexMethod(QGraphicsScene.NoIndex)
        assert slice_root.scene() == slice_scene
        sgv = self.slice_graphics_view
        sgv.setScene(slice_scene)
        sgv.scene_root_item = slice_root
        sgv.setName("SliceView")
        sgv.setScaleFitFactor(0.7)
        self.slice_tool_manager = SliceToolManager(self, slice_root)
        return sgv
    # end def

    def _initEditMenu(self):
        """Initializes the Edit menu
        """
        us = self.controller.undoStack()
        qatrans = QApplication.translate

        action_undo = us.createUndoAction(self)
        action_undo.setText( qatrans("MainWindow", "Undo", None) )
        action_undo.setShortcut( qatrans("MainWindow", "Ctrl+Z", None) )
        self.actionUndo = action_undo

        action_redo = us.createRedoAction(self)
        action_redo.setText( qatrans("MainWindow", "Redo", None) )
        action_redo.setShortcut( qatrans("MainWindow", "Ctrl+Shift+Z", None) )
        self.actionRedo = action_redo

        self.sep = sep = QAction(self)
        sep.setSeparator(True)

        self.menu_edit.insertAction(sep, action_redo)
        self.menu_edit.insertAction(action_redo, action_undo)
        # print([x.text() for x in self.menu_edit.actions()])

        # self.main_splitter.setSizes([400, 400, 180])  # balance main_splitter size
        self.statusBar().showMessage("")
    # end def

    def _finishInit(self):
        """Handle the dockwindow visibility and action checked status.
        The console visibility is explicitly stored in the settings file,
        since it doesn't seem to work if we treat it like a normal dock widget.
        """
        inspector_visible = self.inspector_dock_widget.isVisibleTo(self)
        self.action_inspector.setChecked(inspector_visible)
        path_visible = self.path_dock_widget.isVisibleTo(self)
        self.action_path.setChecked(path_visible)
        slice_visible = self.slice_dock_widget.isVisibleTo(self)

        # NOTE THIS IS ALWAYS FALSE FOR  SOME REASON
        self.action_slice.setChecked(slice_visible)
    # end def

    def getMouseViewTool(self, tool_type_name: str) -> AbstractTool:
        """Give a tool type, return the tool for the view the mouse is over

        Args:
            tool_type_name: the tool which is active or None

        Returns:
            active tool for the view the tool is in
        """
        return_tool = None
        for view in self.views.values():
            if view.underMouse():
                root_item = view.rootItem()
                # print("I am under mouse", view)
                if root_item.manager.isToolActive(tool_type_name):
                    # print("{} is active".format(tool_type_name))
                    return_tool = root_item.manager.activeToolGetter()
                else:
                    # print("no {} HERE!".format(tool_type_name))
                    pass
                break
        return return_tool
    # end def

    def doMouseViewDestroy(self):
        """Destroy the view the mouse is over
        """
        return_tool = None
        for name, view in self.views.items():
            if view.underMouse():
                self.destroyView(name)
    # end def


# end class
