# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Segreg
                                 A QGIS plugin
 This plugin computes spatial and non spatial segregation measures
                              -------------------
        begin                : 2017-01-25
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Sandro Sousa / USP-UFABC
        email                : sandrofsousa@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from qgis.core import *
from PyQt4.QtGui import *
from PyQt4.QtCore import *
from qgis.utils import *
import numpy as np
from scipy.spatial.distance import cdist

# Initialize Qt resources from file resources.py
import resources
# Import the code for the dialog
from segreg_dialog import SegregDialog
import os.path


class Segreg:
    def __init__(self, iface):
        """Constructor.
        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'Segreg_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Segreg')
        self.toolbar = self.iface.addToolBar(u'Segreg')
        self.toolbar.setObjectName(u'Segreg')

        # Other initializations
        self.layers = []                        # Store layers loaded (non geographical)
        self.lwGroups = QListView()
        self.model = QStandardItemModel(self.lwGroups)
        self.lwGroups.setAcceptDrops(True)
        #self.lwGroups = QListWidget()
        #self.lwGroups.setSelectionMode(QAbstractItemView.ExtendedSelection)

        # Segregation measures attributes
        self.attributeMatrix = np.matrix([])    # attributes matrix full size - all columns
        self.location = []                      # x and y coordinates from file (2D lists)
        self.pop = []                           # groups to be analysed [:,4:n] (2D lists)
        self.pop_sum = []                       # sum of population groups from pop (1d array)
        self.locality = []                      # local population intensity for groups
        self.n_location = 0                     # length of list (n lines) (attributeMatrix.shape[0])
        self.n_group = 0                        # number of groups (attributeMatrix.shape[1] - 4)
        self.costMatrix = []                    # scipy cdist distance matrix
        self.track_id = []                      # track ids at string format

        # Local and global internals
        self.local_dissimilarity = []
        self.local_exposure = []
        self.local_entropy = []
        self.local_indexh = []
        self.global_dissimilarity = []
        self.global_exposure = []
        self.global_entropy = []
        self.global_indexh = []

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('Segreg', message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.
        """

        # Create the dialog (after translation) and keep reference
        self.dlg = SegregDialog()

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/Segreg/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'Compute segregation measures'),
            callback=self.run,
            parent=self.iface.mainWindow())

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&Segreg'),
                action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar

    def addLayers(self):
        """
        This function add layers from canvas to check box. It only includes non geographic layers.
        This is due to a restriction at scipy funtion CDIST to calculate distance the matrix.
        """
        # clear box
        self.dlg.cbLayers.clear()

        self.layers = self.iface.legendInterface().layers()
        layer_list = []
        for layer in self.layers:
            # Check if layer is geographic or projected and append projected only
            isgeographic = layer.crs().geographicFlag()
            if isgeographic is False:
                layer_list.append(layer.name())
            else:
                continue
        # update combo box with layers
        self.dlg.cbLayers.addItems(layer_list)

    def addLayerAttributes(self, layer_index):
        """
        This function populates ID and attributes from layer for selection.
        :param layer_index:
        :return:
        """
        # clear list
        self.dlg.cbId.clear()
        self.dlg.lwGroups.clear()
        selectedLayer = self.layers[layer_index]
        
        fields = []
        # get attributes from layer
        for i in selectedLayer.pendingFields():
            fields.append(i.name())
        # Update id and lwGroups combo boxes with fields
        self.dlg.cbId.addItems(fields)
        self.dlg.lwGroups.addItems(fields)

    def selectId(self, layer_index):
        # clear box
        self.dlg.cbId.clear()
        selectedLayer = self.layers[layer_index]
        fields = []
        
        # get attributes from layer
        for field in selectedLayer.pendingFields():
            fields.append(field.name())
        # Update id on combo box with fields
        self.dlg.cbId.addItems(fields)

    def selectGroups(self, layer_index):
        self.dlg.lwGroups.clear()
        selectedLayer = self.layers[layer_index]
        fields = []
    
        # get attributes from layer
        for i in selectedLayer.pendingFields():
            field = QListWidgetItem()
            field.setText(i.name())
            self.dlg.lwGroups.addItem(field)
        #self.dlg.lwGroups.currentRow.setItemSelected(True)

    def confirmButton(self):
        selectedLayerIndex = self.dlg.cbLayers.currentIndex()
        selectedLayer = self.layers[selectedLayerIndex]
        field_names = [str(field.name()) for field in selectedLayer.pendingFields()][1:]

        # populate track_id data
        id_name = self.dlg.cbId.currentText()
        id_values = selectedLayer.getValues(id_name)[0]  #getDoubleValues for float
        id_values = [str(x) for x in id_values]
        self.track_id = np.asarray(id_values)
        self.track_id = self.track_id.reshape((len(id_values), 1))

        # return x and y from polygons centroids
        x_cord = [feat.geometry().centroid().asPoint().x() for feat in selectedLayer.getFeatures()]
        x_cord = np.reshape(x_cord, (len(x_cord), 1))
        y_cord = [feat.geometry().centroid().asPoint().y() for feat in selectedLayer.getFeatures()]
        y_cord = np.reshape(y_cord, (len(y_cord), 1))

        # populate groups data
        groups = []
        for i in field_names:
            values = selectedLayer.getDoubleValues(i)[0]  #getDoubleValues for float
            group = [int(x) for x in values]
            groups.append(group)
        groups = np.asarray(groups).T

        # concatenate values and populate attribute matrix
        data = np.concatenate((x_cord, y_cord, groups), axis=1)
        self.attributeMatrix = np.asmatrix(data)
        n = self.attributeMatrix.shape[1]
        self.location = self.attributeMatrix[:, 0:2]
        self.location = self.location.astype('float')
        self.pop = self.attributeMatrix[:, 2:n]
        self.pop[np.where(self.pop < 0)[0], np.where(self.pop < 0)[1]] = 0
        self.n_group = n - 2
        self.n_location = self.attributeMatrix.shape[0]
        self.pop_sum = np.sum(self.pop, axis=1)

        self.iface.messageBar().pushMessage("Info", "Selection saved", level=QgsMessageBar.INFO, duration=3)

    def runIntensityButton(self):
        # set fixed IDs for radioButtons
        self.dlg.bgWeight.setId(self.dlg.gauss, 1)
        self.dlg.bgWeight.setId(self.dlg.bisquar, 2)
        self.dlg.bgWeight.setId(self.dlg.mvwind, 3)

        # set parameters to call locality matrix
        weight = self.dlg.bgWeight.checkedId()
        bw = int(self.dlg.leBandwidht.text())

        self.cal_localityMatrix(bw, weight)
        self.iface.messageBar().pushMessage("Info", "Matrix of shape %s computed" % str(self.locality.shape),
                                            level=QgsMessageBar.INFO, duration=4)

    def runMeasuresButton(self):
        """
        This function call the functions to compute local and global measures. It populates internals
        with lists holding the results for saving.
        """
        # call local and global dissimilarity measures
        if self.dlg.diss_local.isChecked() is True:
            self.cal_localDissimilarity()
        if self.dlg.diss_global.isChecked() is True:
            self.cal_globalDissimilarity()

        # call local and global exposure/isolation measures
        if self.dlg.expo_local.isChecked() is True:
            self.cal_localExposure()
        if self.dlg.expo_global.isChecked() is True:
            self.cal_globalExposure()

        # call local and global entropy measures
        if self.dlg.entro_local.isChecked() is True:
            self.cal_localEntropy()
        if self.dlg.entro_global.isChecked() is True:
            self.cal_globalEntropy()

        # call local and global index H measures
        if self.dlg.idxh_local.isChecked() is True:
            self.cal_localIndexH()
        if self.dlg.idxh_global.isChecked() is True:
            self.cal_globalIndexH()

    def getWeight(self, distance, bandwidth, weightmethod=1):
        """
        This function computes the weights for neighborhood. Default value is Gaussian(1)
        :param distance: distance in meters to be considered for weighting
        :param bandwidth: bandwidth in meters selected to perform neighborhood
        :param weightmethod: method to be used: 1-gussian , 2-bi square and 3-moving window
        :return: weight value for internal use
        """
        distance = np.asarray(distance.T)
        if weightmethod == 1:
            weight = np.exp((-0.5) * (distance / bandwidth) * (distance / bandwidth))
        elif weightmethod == 2:
            weight = (1 - (distance / bandwidth) * (distance / bandwidth)) * (
            1 - (distance / bandwidth) * (distance / bandwidth))
            sel = np.where(distance > bandwidth)
            weight[sel[0]] = 0
        elif weightmethod == 3:
            weight = 1
            sel = np.where(distance > bandwidth)
            weight[sel[0], :] = 0
        else:
            raise Exception('Invalid weight method selected!')
        return weight

    def cal_localityMatrix(self, bandwidth=5000, weightmethod=1):
        """
        This function calculate the local population intensity for all groups.
        :param bandwidth: bandwidth for neighborhood in meters
        :param weightmethod: 1 for gaussian, 2 for bi-square and empty for moving window
        :return: 2d array like with population intensity for all groups
        """
        n_local = self.location.shape[0]
        n_subgroup = self.pop.shape[1]
        locality_temp = np.empty([n_local, n_subgroup])
        for index in range(0, n_local):
            for index_sub in range(0, n_subgroup):
                cost = cdist(self.location[index, :], self.location)
                weight = self.getWeight(cost, bandwidth, weightmethod)
                locality_temp[index, index_sub] = np.sum(weight * np.asarray(self.pop[:, index_sub]))/np.sum(weight)
        self.locality = locality_temp
        self.locality[np.where(self.locality < 0)[0], np.where(self.locality < 0)[1]] = 0

    def cal_localDissimilarity(self):
        """
        Compute local dissimilarity for all groups.
        :return: 1d array like with results for all groups, size of localities
        """
        if len(self.locality) == 0:
            lj = np.ravel(self.pop_sum)
            tjm = np.asarray(self.pop) * 1.0 / lj[:, None]
            tm = np.sum(self.pop, axis=0) * 1.0 / np.sum(self.pop)
            index_i = np.sum(np.asarray(tm) * np.asarray(1 - tm))
            pop_total = np.sum(self.pop)
            local_diss = np.sum(1.0 * np.array(np.fabs(tjm - tm)) *
                                np.asarray(self.pop_sum).ravel()[:, None] / (2 * pop_total * index_i), axis=1)
        else:
            lj = np.asarray(np.sum(self.locality, axis=1))
            tjm = self.locality * 1.0 / lj[:, None]
            tm = np.sum(self.pop, axis=0) * 1.0 / np.sum(self.pop)
            index_i = np.sum(np.asarray(tm) * np.asarray(1 - tm))
            pop_total = np.sum(self.pop)
            local_diss = np.sum(1.0 * np.array(np.fabs(tjm - tm)) *
                                np.asarray(self.pop_sum).ravel()[:, None] / (2 * pop_total * index_i), axis=1)
        local_diss = np.nan_to_num(local_diss)
        local_diss = np.asmatrix(local_diss).transpose()
        self.local_dissimilarity = local_diss

    def cal_globalDissimilarity(self):
        """
        This function call local dissimilarity and compute the sum from individual values.
        :return: display global value
        """
        local_diss = self.local_dissimilarity
        self.global_dissimilarity = np.sum(local_diss)

    def cal_localExposure(self):
        """
        This function computes the local exposure index of group m to group n.
        in situations where m=n, then the result is the isolation index.
        :return: 2d list with individual indexes
        """
        m = self.n_group
        j = self.n_location
        exposure_rs = np.zeros((j, (m * m)))
        if len(self.locality) == 0:
            local_expo = np.asarray(self.pop) * 1.0 / np.asarray(np.sum(self.pop, axis=0)).ravel()
            locality_rate = np.asarray(self.pop) * 1.0 / np.asarray(np.sum(self.pop, axis=1)).ravel()[:, None]
            for i in range(m):
                exposure_rs[:, ((i * m) + 0):((i * m) + m)] = np.asarray(locality_rate) * \
                                                              np.asarray(local_expo[:, i]).ravel()[:, None]
        else:
            local_expo = np.asarray(self.pop) * 1.0 / np.asarray(np.sum(self.pop, axis=0)).ravel()
            locality_rate = np.asarray(self.locality) * 1.0 / np.asarray(np.sum(self.locality, axis=1)).ravel()[:, None]
            for i in range(m):
                exposure_rs[:, ((i * m) + 0):((i * m) + m)] = np.asarray(locality_rate) * \
                                                              np.asarray(local_expo[:, i]).ravel()[:, None]
        exposure_rs[np.isinf(exposure_rs)] = 0
        exposure_rs[np.isnan(exposure_rs)] = 0
        exposure_rs = np.asmatrix(exposure_rs)
        self.local_exposure = exposure_rs

    def cal_globalExposure(self):
        """
        This function call local exposure function and sum the results for the global index.
        :return: displays global number result
        """
        m = self.n_group
        local_exp = self.local_exposure
        global_exp = np.sum(local_exp, axis=0)
        global_exp = global_exp.reshape((m, m))
        self.global_exposure = global_exp

    def cal_localEntropy(self):
        """
        This function computes the local entropy score for a unit area Ei (diversity). A unit within the
        metropolitan area, such as a census tract. If population intensity was previously computed,
        the spatial version will be returned, else the non spatial version will be selected (raw data).
        :return: 2d array with local indices
        """
        if len(self.locality) == 0:
            proportion = np.asarray(self.pop / self.pop_sum)
        else:
            proportion = np.asarray(self.locality / np.sum(self.locality))
        entropy = proportion * np.log(1 / proportion)
        entropy[np.isnan(entropy)] = 0
        entropy[np.isinf(entropy)] = 0
        entropy = np.sum(entropy, axis=1)
        entropy = entropy.reshape((self.n_location, 1))
        self.local_entropy = entropy

    def cal_globalEntropy(self):
        """
        This function computes the global entropy score E (diversity). A metropolitan area's entropy score.
        :return: diversity score
        """
        group_score = []
        if len(self.locality) == 0:
            pop_total = np.sum(self.pop_sum)
            prop = np.asarray(np.sum(self.pop, axis=0))[0]
        else:
            pop_total = np.sum(self.locality)
            prop = np.asarray(np.sum(self.locality, axis=0))
        for group in prop:
            group_idx = group / pop_total * np.log(1 / (group / pop_total))
            group_score.append(group_idx)
        global_entro = np.sum(group_score)
        self.global_entropy = global_entro

    def cal_localIndexH(self):
        """
        This function computes the local entropy index H for all localities. The functions cal_localEntropy() for
        local diversity and cal_globalEntropy for global entropy are called as input. If population intensity
        was previously computed, the spatial version will be returned, else the non spatial version will be
        selected (raw data).
        :return: array like with scores for n groups (size groups)
        """
        local_entropy = self.local_entropy
        global_entropy = self.global_entropy
        if len(self.locality) == 0:
            et = np.asarray(global_entropy * np.sum(self.pop_sum))
            eei = np.asarray(global_entropy - local_entropy)
            h_local = eei * np.asarray(self.pop_sum) / et
        else:
            et = np.asarray(global_entropy * np.sum(self.locality))
            eei = np.asarray(global_entropy - local_entropy)
            h_local = eei * np.sum(self.locality) / et
        self.local_indexh = h_local

    def cal_globalIndexH(self):
        """
        Function to compute global index H returning the sum of local values. The function cal_localIndexH is
        called as input for sum of individual values.
        :return: values with global index for each group.
        """
        h_local = self.local_indexh
        h_global = np.sum(h_local, axis=0)
        self.global_indexh = h_global

    # def clicked(self, item):
    #     #self.dlg.lwGroups.item.setBackgroundColor("blue")
    #     QMessageBox.information(self, "lwGroups", "You clicked: "+item.text())

    def test(self):
        self.iface.messageBar().pushMessage("Info", str(self.global_indexh), level=QgsMessageBar.INFO, duration=4)

    def joinResultsData(self):
        """ Function to join results on a unique matrix and assign names for columns"""
        names = ['id','x','y']
        for i in range(self.n_group):
            names.append('group_' + str(i))

        measures_computed = []
        if len(self.locality) != 0:
            measures_computed.append('self.locality')
            for i in range(self.n_group):
                names.append('intens_' + str(i))

        if len(self.local_exposure) != 0:
            measures_computed.append('self.local_exposure')
            for i in range(self.n_group):
                for j in range(self.n_group):
                    if i == j:
                        names.append('iso_' + str(i) + str(j))
                    else:
                        names.append('exp_' + str(i) + str(j))

        if len (self.local_dissimilarity) != 0:
            measures_computed.append('self.local_dissimilarity')
            names.append('dissimil')

        if len (self.local_entropy) != 0:
            measures_computed.append('self.local_entropy')
            names.append('entropy')

        if len (self.local_indexh) != 0:
            measures_computed.append('self.local_indexh')
            names.append('indexh')

        output_labels = tuple([eval(x) for x in measures_computed])
        computed_results = np.concatenate(output_labels, axis=1)
        results_matrix = np.concatenate((self.track_id, self.attributeMatrix, computed_results), axis=1)
        labels = str(', '.join(names))
        measures_computed[:] = []
        return results_matrix, labels

    def saveResults(self):
        """ Function to save results to a local file."""
        filename = QFileDialog.getSaveFileName(self.dlg, "Select output file ", "", "*.csv")
        self.dlg.leOutput.setText(filename)
        path = self.dlg.leOutput.text()
        result = self.joinResultsData()
        np.savetxt(path, result[0], header=result[1], delimiter=',', newline='\n', fmt="%s")

        # save global results to an alternate local file
        with open("%s_global.txt" % path, "w") as f:
            f.write('Global dissimilarity: ' + str(self.global_dissimilarity))
            f.write('\nGlobal entropy: ' + str(self.global_entropy))
            f.write('\nGlobal Index H: \n' + str(self.global_indexh))
            f.write('\nGlobal isolation/exposure: \n')
            f.write(str(self.global_exposure))

        # clear local variables after save
        self.local_dissimilarity = []
        self.local_exposure = []
        self.local_entropy = []
        self.local_indexh = []

    def run(self):
        """Run method to call dialog and connect interface with functions"""
        # show the dialog
        self.dlg.show()

        # populate layers list with a projected CRS
        self.addLayers()

        # populate initial view with first layer
        selectedLayerIndex = self.dlg.cbLayers.currentIndex()
        self.addLayerAttributes(selectedLayerIndex)

        # initialize dialog loop to add attributes for display
        self.dlg.cbLayers.currentIndexChanged["int"].connect(self.addLayerAttributes)

        # save selected values from user and populate internals
        self.dlg.pbConfirm.clicked.connect(self.confirmButton)

        # run population intensity calculation
        self.dlg.pbRunIntensity.clicked.connect(self.runIntensityButton)

        # run measures from selected check boxes
        self.dlg.pbRunMeasures.clicked.connect(self.runMeasuresButton)

        # run dialog to select and save output file
        self.dlg.leOutput.clear()
        self.dlg.pbOpenPath.clicked.connect(self.saveResults)

        # # position on current layer selected from list view
        # if self.layers is None:
        #self.iface.messageBar().pushMessage("Info", "%s" % var, level=QgsMessageBar.INFO, duration=3)
        
        #self.dlg.cbLayers.currentIndexChanged["int"].connect(self.selectId)
        #self.dlg.cbLayers.currentIndexChanged["int"].connect(self.selectGroups)

        #self.dlg.connect(self.lwGroups, SIGNAL("itemSelectionChanged()"), self.clicked)

        # Run the dialog event loop
        self.dlg.exec_()