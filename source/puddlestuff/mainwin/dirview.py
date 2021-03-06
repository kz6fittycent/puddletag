# -*- coding: utf-8 -*-
from PyQt4.QtGui import *
from PyQt4.QtCore import *
from copy import deepcopy
from functools import partial
import os, shutil, pdb, mutex
from puddlestuff.puddleobjects import (PuddleConfig, PuddleThread, 
    issubfolder, PuddleHeader)
from puddlestuff.constants import LEFTDOCK, HOMEDIR, QT_CONFIG
mutex = mutex.mutex()
qmutex = QMutex()
from puddlestuff.translations import translate
from puddlestuff.tagmodel import has_previews
try:
    from puddlestuff.puddlesettings import (load_gen_settings,
        save_gen_settings)
except ImportError:
    pass

class DirView(QTreeView):
    """The treeview used to select a directory."""

    def __init__(self, parent = None, subfolders = False, status=None):
        QTreeView.__init__(self,parent)
        dirmodel = QDirModel()
        dirmodel.setSorting(QDir.IgnoreCase)
        dirmodel.setFilter(QDir.Dirs | QDir.NoDotAndDotDot)
        dirmodel.setReadOnly(False)
        dirmodel.setLazyChildCount(False)
        dirmodel.setResolveSymlinks(False)
        header = PuddleHeader(Qt.Horizontal, self)
        self.setHeader(header)
        self.header().setResizeMode(QHeaderView.ResizeToContents)

        self.setModel(dirmodel)
        [self.hideColumn(column) for column in range(1,4)]

        self.header().hide()
        self.subfolders = subfolders
        self.setSelectionMode(self.ExtendedSelection)
        self._lastselection = 0 #If > 0 appends files. See selectionChanged
        self._load = True #If True a loadFiles signal is emitted when
                          #an index is clicked. See selectionChanged.
        self.setDragEnabled(False)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self._dropaction = Qt.MoveAction
        self._threadRunning = False

        self._select = True
        
        self.connect(self, SIGNAL('expanded(const QModelIndex &)'),
            lambda discarded: self.resizeColumnToContents(0))

    def checkPreviews(self, deselected):
        """Confirm to user if any file have previewes.

        If any currently loaded files have previews then the user
        is asked to confirm whether they want to change to a new dir.
        Returns True if the user cancels the action, False if
        the user chooses to go ahead or there are no un-commited previews.
        """
        msg = translate('Previews', 'Some files have uncommited previews. '
            'Changes will be lost once you load a directory. <br />'
            'Do you still want to load a new directory?<br />')
        if not has_previews(parent=self.parentWidget(), msg=msg):
            return False
        select = self._select
        self._select = False
        smodel = self.selectionModel()
        smodel.blockSignals(True)
        smodel.clear()
        smodel.select(deselected, smodel.Select)
        smodel.blockSignals(False)
        self._select = select
        return True

    def clearSelection(self, *args):
        self.blockSignals(True)
        self.selectionModel().clearSelection()
        self.blockSignals(False)
        self.emit(SIGNAL('removeFolders'), [], True)
    
    def contextMenuEvent(self, event):

        connect = lambda o,s: self.connect(o, SIGNAL('triggered()'), s)
        
        menu = QMenu(self)
        refresh = QAction(translate("Dirview",
            'Refresh Directory'), self)

        index = self.indexAt(event.pos())
        connect(refresh, lambda: self.model().refresh(index))
        
        header = self.header()
        if self.header().isHidden():
            show_header = QAction(translate("Dirview",
                'Show Header'), self)
            connect(show_header, header.show)
        else:
            show_header = QAction(translate("Dirview",
                'Hide Header'), self)
            connect(show_header, header.hide)
        
        open_dir = QAction(translate(
            'Dirview', 'Open in File Manager'), self)
        connect(open_dir, lambda: self.openExtern(index))
        
        menu.addAction(refresh)
        menu.addAction(show_header)
        menu.addAction(open_dir)

        menu.exec_(event.globalPos())
        super(DirView, self).contextMenuEvent(event)

    def dirMoved(self, dirs):
        if not self.isVisible():
            return
        self._load = False
        model = self.model()
        selectindex = self.selectionModel().select
        getindex = model.index
        exists = os.path.exists

        parents = set([os.path.dirname(z[0]) for z in dirs])

        def get_str(f):
            return model.filePath(f).toLocal8Bit().data()

        selected = map(get_str, self.selectedIndexes())

        for p in parents:
            if exists(p):
                i = getindex(p)
                while not i.isValid():
                    p = os.path.dirname(p)
                    i = getindex(p)
                model.refresh(i)
        
        for d in [z[1] for z in dirs] + selected:
            if isinstance(d, str):
                d = QString.fromLocal8Bit(d)
            self.selectIndex(getindex(d))
        self._load = True

    def loadSettings(self):
        settings = QSettings(QT_CONFIG, QSettings.IniFormat)
        header = self.header()
        header.restoreState(settings.value('dirview/header').toByteArray())
        hide = settings.value('dirview/hide', QVariant(True)).toBool()
        self.setHeaderHidden(hide)

        if self.isVisible() == False:
            return
        
        cparser = PuddleConfig()
        d = cparser.get('main', 'lastfolder', '/')
        while not os.path.exists(d):
            d = os.path.dirname(d)
            if not d:
                return

        def expand_thread_func():
            index = self.model().index(d)
            parents = []
            while index.isValid():
                parents.append(index)
                index = index.parent()
            return parents
        
        def expandindexes(indexes):
            self.setEnabled(False)
            [self.expand(index) for index in indexes]
            self.setEnabled(True)
        
        thread = PuddleThread(expand_thread_func, self)
        thread.connect(thread, SIGNAL('threadfinished'), expandindexes)
        thread.start()
    
    def mousePressEvent(self, event):
        if event.buttons() == Qt.RightButton:
            return
        else:
            super(DirView, self).mousePressEvent(event)

    def openExtern(self, index):
        if index.isValid():
            filename = self.model().filePath(index)
            QDesktopServices.openUrl(QUrl.fromLocalFile(filename))

    def selectDirs(self, dirlist):
        if self._threadRunning:
            return
        if not self.isVisible():
            return
        if not self._select:
            self._select = True
            return
        load = self._load
        self._load = False
        if not dirlist:
            self._load = False
            self.selectionModel().clear()
            self._load = load
            return

        if isinstance(dirlist, basestring):
            dirlist = [dirlist]
        self._threadRunning = True
        self.setEnabled(False)
        self.selectionModel().clear()
        selectindex = self.selectionModel().select
        getindex = self.model().index
        parent = self.model().parent

        def func():
            toselect = []
            toexpand = []
            for d in dirlist:
                if not os.path.exists(d):
                    continue
                if isinstance(d, str):
                    try:
                        d = unicode(d, 'utf8')
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        pass
                index = getindex(d)
                toselect.append(index)
                i = parent(index)
                parents = []
                while i.isValid():
                    parents.append(i)
                    i = parent(i)
                toexpand.extend(parents)
            return (toselect, toexpand)

        def finished(val):
            qmutex.lock()
            select = val[0]
            expand = val[1]
            if select:
                self.setCurrentIndex(select[0])
                self.scrollTo(select[0])
            [selectindex(z, QItemSelectionModel.Select) for z in select]
            if expand:
                [self.expand(z) for z in expand]
            self.blockSignals(False)
            self.setEnabled(True)
            self._load = load
            self._threadRunning = False
            qmutex.unlock()
        dirthread = PuddleThread(func, self)
        self.connect(dirthread, SIGNAL('threadfinished'), finished)
        dirthread.start()
    
    def saveSettings(self):
        settings = QSettings(QT_CONFIG, QSettings.IniFormat)
        settings.setValue('dirview/header', 
            QVariant(self.header().saveState()))
        settings.setValue('dirview/hide', QVariant(self.isHeaderHidden()))

    def selectionChanged(self, selected, deselected):
        QTreeView.selectionChanged(self, selected, deselected)
        if not self._load:
            self._lastselection = len(self.selectedIndexes())
            return
            
        getfilename = self.model().filePath
        dirs = list(set([getfilename(i).toLocal8Bit().data() for
            i in selected.indexes()]))
        old = list(set([getfilename(i).toLocal8Bit().data() for
            i in deselected.indexes()]))
        if self._lastselection:
            if len(old) == self._lastselection:
                append = False
            else:
                append = True
        else:
            append = False
        dirs = list(set(dirs).difference(old))
        if old:
            self.emit(SIGNAL('removeFolders'), old, False)

        if self.checkPreviews(deselected):
            return
        if dirs:
            self.emit(SIGNAL('loadFiles'), None, dirs, append)
        self._lastselection = len(self.selectedIndexes())
        self._select = False

    def selectIndex(self, index):
        if not index.isValid():
            return
        self.selectionModel().select(index, QItemSelectionModel.Select)
        parent = index.parent()
        while parent.isValid():
            self.expand(index)
            parent = parent.parent()
        

class DirViewWidget(QWidget):
    def __init__(self, parent = None, subfolders = False, status=None):
        super(DirViewWidget, self).__init__(parent)
        self._status = status
        
        self.dirview = DirView(self, subfolders, status)
        self.connect(self.dirview, SIGNAL('loadFiles'), SIGNAL('loadFiles'))
        self.connect(self.dirview, SIGNAL('removeFolders'), SIGNAL('removeFolders'))

        self.receives = [
            ('dirschanged', self.dirview.selectDirs),
            ('dirsmoved', self.dirview.dirMoved),
            ]
        self.emits = ['loadFiles', 'removeFolders']

        self.subfolderCheck = QCheckBox(translate('Dirview', 'Subfolders'),
            self)
        self.connect(self.subfolderCheck, SIGNAL('stateChanged(int)'),
            self.setSubFolders)

        layout = QVBoxLayout()
        layout.addWidget(self.dirview, 1)
        layout.addWidget(self.subfolderCheck, 0)
        self.setLayout(layout)

    def loadSettings(self):
        self.dirview.loadSettings()
        self.subfolderCheck.blockSignals(True)
        if load_gen_settings([('Su&bfolders', True)])[0][1]:
            self.subfolderCheck.setChecked(True)
        else:
            self.subfolderCheck.setChecked(False)
        self.subfolderCheck.blockSignals(False)

    def saveSettings(self):
        self.dirview.saveSettings()

    def setSubFolders(self, check):
        if check == Qt.Checked:
            value = True
        else:
            value = False
        self.dirview.subfolders = value
        save_gen_settings({'Su&bfolders': value})
        self._status['table'].subFolders = value


control = ('Filesystem', DirViewWidget, LEFTDOCK, True)
