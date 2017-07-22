import logging
from collections import OrderedDict
import random
import os
import math
import numpy as np
import theano
import time
import gc
import datetime
import multiprocessing as mp
import nibabel as nib

from utils.sampleNii import getSamplesForSubEpoch, sampleWholeBrain
from utils.loadNiiData import loadSinglePatientData
from utils.general import logMessage, logTable
from utils.metrics import voxleWiseMetrics
from models.sectorNet import SectorNet
from models.baseNet import BaseNet
from models.dilated3DNet import Dilated3DNet





def generateNetwork(configFile, onceRunningDir):

    logger = logging.getLogger(__name__)

    # Get config infomation
    configInfo = {}
    execfile(configFile, configInfo)

    # Choose the network type
    # ====================================================================================
    # The networksDict should conresponding to the import statement. 
    networksDict = {'sectorNet': SectorNet,
                    'baseNet': BaseNet, 
                    'dilated3DNet' : Dilated3DNet}

    networkType = configInfo['networkType']
    networkClass = networksDict[networkType]
    # ====================================================================================

    # Generate the network
    # ====================================================================================
    preTrainedWeights = configInfo['preTrainedWeights']
    if preTrainedWeights == '':
        message = 'We will create a new network'
        logger.info(logMessage(' ', message))
    else:
        message = 'We will use a pre trained network'
        logger.info(logMessage(' ', message))

    message = 'Creating {}'.format(configInfo['networkName'])
    logger.info(logMessage('#', message))
    network = networkClass(configFile, onceRunningDir)
    assert network.networkType == networkType
    message = 'Created {}'.format(networkType)
    logger.info(logMessage('#', message))
    # =====================================================================================

    return network



def trainNetwork(network, configFile):

    logger = logging.getLogger(__name__)

    message = 'Training {}'.format(network.networkType)
    logger.info(logMessage('#', message))

    # Get config infomation
    configInfo = {}
    execfile(configFile, configInfo)

    # Network information
    # ==============================================================================
    # Just for rebuild the network than we can get the network summary conresponding
    # the trainSampleSize
    # Read network information
    trainSampleSize = configInfo['trainSampleSize']
    kernelNumList = configInfo['kernelNumList']
    kernelShapeList = configInfo['kernelShapeList']
    concatLayerList = configInfo['concatLayerList']
    dilatedFactorList = configInfo['dilatedFactorList']
    networkType = network.networkType
    receptiveField = network.receptiveField
    networkSummary = network.summary(trainSampleSize)
    # ------------------------------------------------------------------------------
    # Logger network summary
    message = 'Network Summary'
    logger.info(logMessage('*', message))
    logger.info(logTable(networkSummary))
    logger.info(logMessage('-', '-'))
    tableRowList = []
    tableRowList.append(['-', '-'])
    tableRowList.append(['Kernel Number List', kernelNumList])
    tableRowList.append(['Kernel Shape List', kernelShapeList])
    tableRowList.append(['Concat Layer List', concatLayerList])
    tableRowList.append(['Dilated Factor List', dilatedFactorList])
    tableRowList.append(['Network Type', networkType])
    tableRowList.append(['Receptive Field', receptiveField])
    tableRowList.append(['-', '-'])

    logger.info(logTable(tableRowList))
    logger.info(logMessage('*', '*'))
    # =============================================================================

    # Training and validation data information
    # =============================================================================
    # Read training and validation data information
    imageFolder = configInfo['imageFolder']
    valImageFolder = configInfo['valImageFolder']
    imageGrades = configInfo['imageGrades']
    numOfPatients = configInfo['numOfPatients']
    modals = configInfo['modals']
    useROI = configInfo['useROI']
    normType = configInfo['normType']
    weightMapType = configInfo['weightMapType']
    priviousResult = configInfo['priviousResult']
    # ----------------------------------------------------------------------------
    # Logger training and validation data information
    message = 'Training and Validation Data Summary'
    logger.info(logMessage('*', message))

    tableRowList = []
    tableRowList.append(['-', '-'])
    tableRowList.append(['Image Folder', imageFolder])
    tableRowList.append(['Validation Image Folder', valImageFolder])
    tableRowList.append(['Image Grades', imageGrades])
    tableRowList.append(['Number of Patients', numOfPatients])
    tableRowList.append(['Modals', modals])
    tableRowList.append(['Use ROI', useROI])
    tableRowList.append(['Normalization Type', normType])
    tableRowList.append(['Weight Map Type', weightMapType])
    tableRowList.append(['Privious Step Result', priviousResult])
    tableRowList.append(['-', '-'])

    logger.info(logTable(tableRowList))
    logger.info(logMessage('*', '*'))
    # ===========================================================================

    # Training and validation setting infomation
    # ===========================================================================
    # Read training and validation setting information
    learningRate = configInfo['learningRate']
    learningRateDecay = configInfo['learningRateDecay']
    weightDecay = configInfo['weightDecay']
    optimizer = configInfo['optimizer']
    dropoutRates = configInfo['dropoutRates']
    usePoolToSample = configInfo['usePoolToSample']
    numOfEpochs = configInfo['numOfEpochs']
    numOfSubEpochs = configInfo['numOfSubEpochs']
    batchSize = configInfo['batchSize']
    trainSampleSize = configInfo['trainSampleSize']
    valSampleSize = configInfo['valSampleSize']
    numOfTrainSamplesPerSubEpoch = configInfo['numOfTrainSamplesPerSubEpoch']
    weightsDir = network.weightsDir
    valResultDir = network.valResultDir
    assert batchSize < numOfTrainSamplesPerSubEpoch
    # ---------------------------------------------------------------------------
    # Logger training and validation setting infomation
    message = 'Training and Validation setting Summary'
    logger.info(logMessage('*', message))

    tableRowList = []
    tableRowList.append(['-', '-'])
    tableRowList.append(['Learning Rate', learningRate])
    tableRowList.append(['Learning Rate Decay', learningRateDecay])
    tableRowList.append(['Weight Decay', weightDecay])
    tableRowList.append(['Optimizer', optimizer])
    tableRowList.append(['Dropout Rates', dropoutRates])
    tableRowList.append(['Wheather Use MultiProcess to Sample', usePoolToSample])
    tableRowList.append(['Number of Epochs', numOfEpochs])
    tableRowList.append(['Number of Subepochs', numOfSubEpochs])
    tableRowList.append(['Batch Size', batchSize])
    tableRowList.append(['Training Samples Size', trainSampleSize])
    tableRowList.append(['Validation Samples Size', valSampleSize])
    tableRowList.append(['Number of Training Samples for Subepoch', 
                         numOfTrainSamplesPerSubEpoch])
    tableRowList.append(['Folder to Store Weights During Training', weightsDir])
    tableRowList.append(['Validation Result Folder', valResultDir])
    tableRowList.append(['-', '-'])

    logger.info(logTable(tableRowList))
    logger.info(logMessage('*', '*'))
    # ===========================================================================

    # Prepare patients file dir list
    # ===========================================================================
    # Read patients dir list
    patientsDirList = []
    valpatientsDirList = []

    gradeDirList = [os.path.join(imageFolder, grade) for grade in imageGrades]
    valGradeDirList = [os.path.join(valImageFolder, grade) for grade in imageGrades]

    for gradeDir in gradeDirList:
        patientsDirList += [os.path.join(gradeDir, patient) 
                            for patient in os.listdir(gradeDir)]
   
    for gradeDir in valGradeDirList:
        valpatientsDirList += [os.path.join(gradeDir, patient) 
                               for patient in os.listdir(gradeDir)]

    # Make sure there are no same elements in the patientsDirList
    assert len(patientsDirList) == len(set(patientsDirList))
    random.shuffle(patientsDirList)
    # numOfPatients == -1 stands for using all data
    if numOfPatients != -1: 
        patientsDirList = patientsDirList[:numOfPatients]
    # ---------------------------------------------------------------------------

    message = 'Use {} cases for training '.format(len(patientsDirList))
    message += 'and {} cases for validation'.format(len(valpatientsDirList))
    logger.info(logMessage(' ', message))
   
    # ===========================================================================

    # Prepare a table to record and show training and validation results
    # ===========================================================================
    trainTRowList = []
    trainTRowList.append(['-', '-', '-', '-', '-', '-'])
    trainTRowList.append(['EPOCH',      'SUBEPOCH',    'Train Time', 
                          'Train Loss', 'Train ACC',   'Sampling Time'])
    trainTRowList.append(['-', '-', '-', '-', '-', '-'])
    # ***************************************************************************
    valTRowList = []
    valTRowList.append(['-', '-', '-', '-', '-', '-', '-', '-', '-', '-', '-'])
    valTRowList.append(['EPOCH',        'Val Time', 
                        'CT Dice',      'CT Sens',     'CT Spec', 
                        'Core Dice',    'Core Sens',   'Core Spec', 
                        'Eh Dice',      'Eh Sens',     'Eh Spec',])
    valTRowList.append(['-', '-', '-', '-', '-', '-', '-', '-', '-', '-', '-'])
    # ===========================================================================

    # Train and Val
    # ##################################################################################################
    for epIdx in xrange(numOfEpochs):

        message = 'EPOCH: {}/{}'.format(epIdx + 1, numOfEpochs)
        logger.info(logMessage('+', message))

        epOutputDir = os.path.join(valResultDir, 'Ep' + str(epIdx + 1))
        os.mkdir(epOutputDir)

        # Initial some epoch recordor
        # ==============================================================================================
        trainEpLoss = 0
        trainEpACC = 0
        trainEpBatchNum = 0
        # **********************************************************************************************
        epTrainSampleTime = 0
        epTrainTime = 0
        # ==============================================================================================

        for subEpIdx in xrange(numOfSubEpochs):

            message = 'SUBEPOCH: {}/{}'.format(subEpIdx + 1, numOfSubEpochs)
            logger.info(logMessage('-', message))

            subEpOutputDir = os.path.join(epOutputDir, 'SubEp' + str(subEpIdx + 1))
            os.mkdir(subEpOutputDir)

            # Training
            # ==========================================================================================
            # Train sample training data
            trainSampleTime = time.time()
            message = 'Sampling Training Data'
            logger.info(logMessage('-', message))
            # ------------------------------------------------------------------------------------------
            trainSampleAndLabelList = getSamplesForSubEpoch(numOfTrainSamplesPerSubEpoch,
                                                            patientsDirList,
                                                            useROI,
                                                            modals,
                                                            normType,
                                                            trainSampleSize ,
                                                            receptiveField,
                                                            weightMapType,
                                                            usePoolToSample,
                                                            priviousResult)
            # ------------------------------------------------------------------------------------------
            trainSamplesList, trainLabelsList = trainSampleAndLabelList
            trainSampleTime = time.time() - trainSampleTime
            epTrainSampleTime += trainSampleTime
            # -----------------------------------------------------------------------------------------
            # Prepare for train batch loop
            trainBatchIdxList = [trainBatchIdx for trainBatchIdx 
                                 in xrange(0, numOfTrainSamplesPerSubEpoch, batchSize)]

            # For the last batch not to be too small.
            trainBatchIdxList[-1] = numOfTrainSamplesPerSubEpoch
            assert len(trainBatchIdxList) > 1
            trainBatchNum = len(trainBatchIdxList[:-1])
            # -----------------------------------------------------------------------------------------
            # Training batch loop
            trainSubEpLoss = 0
            trainSubEpACC = 0
            trainSubEpBatchNum = 0
            trainTime = time.time()
            message = 'Training'
            logger.info(logMessage(':', message))
            # ........................................................................................
            for trainBatchIdx in xrange(trainBatchNum):

                # For showing progress
                if trainBatchIdx % 100 == 0:
                    logger.info('Ep {} SubEp {} Batch {}/{}'.format(epIdx + 1, 
                                                                    subEpIdx + 1, 
                                                                    trainBatchIdx + 1, 
                                                                    trainBatchNum))

                # Just for clear.
                trainStartIdx = trainBatchIdxList[trainBatchIdx]
                trainEndIdx = trainBatchIdxList[trainBatchIdx + 1]

                trainSamplesBatch = trainSamplesList[trainStartIdx:trainEndIdx]
                trainSamplesBatch = np.asarray(trainSamplesBatch, dtype = theano.config.floatX)

                trainLabelsBatch = trainLabelsList[trainStartIdx:trainEndIdx]
                trainLabelsBatch = np.asarray(trainLabelsBatch, dtype = 'int32')

                trainBatchLoss, trainBatchAcc = network.trainFunction(trainSamplesBatch, trainLabelsBatch)
                # Record subepoch training results.
                trainSubEpLoss += trainBatchLoss
                trainSubEpACC += trainBatchAcc
                trainSubEpBatchNum += 1

                del trainSamplesBatch, trainLabelsBatch

            trainTime = time.time() - trainTime
            epTrainTime += trainTime
            # ........................................................................................
            # Release source
            del trainSamplesList[:], trainLabelsList[:]
            del trainSamplesList, trainLabelsList
            gc.collect()
            # ========================================================================================

            
            # Record epooch results and compute subepoch results
            # =========================================================================================
            # Record epooch training results and compute training subepoch results
            # -----------------------------------------------------------------------------------------
            # Record training epoch results
            trainEpLoss += trainSubEpLoss
            trainEpACC += trainSubEpACC
            trainEpBatchNum += trainSubEpBatchNum
            # -----------------------------------------------------------------------------------------
            # Compute training subepoch results
            trainSubEpLoss /= trainSubEpBatchNum
            trainSubEpACC /= trainSubEpBatchNum
            # *****************************************************************************************
            # =========================================================================================

            # Recording for subEpoch row of table
            # =========================================================================================
            indexColumn = epIdx + 1 if subEpIdx == 0 else ''
            # Recording for subEpoch row of training table
            # -----------------------------------------------------------------------------------------
            trainSampleTime = '{:.3}'.format(trainSampleTime)
            trainTime = '{:.3}'.format(trainTime)
            trainSubEpLoss = '{:.6f}'.format(trainSubEpLoss)
            trainSubEpACC = '{:.6f}'.format(trainSubEpACC)
            
            trainTRowList.append([indexColumn,      subEpIdx + 1,      trainTime,
                                 trainSubEpLoss,   trainSubEpACC,     trainSampleTime])
            # =========================================================================================

            # Subepoch logger
            # =========================================================================================
            message = 'Subepoch: {}/{} '.format(subEpIdx + 1, numOfSubEpochs)
            message += ' Train Loss: {}, '.format(trainSubEpLoss)
            message += ' Train ACC: {}'.format(trainSubEpACC)
            logger.info(logMessage('-', message))
            # =========================================================================================

        # Validation
        # ========================================================================================
        valEpCTDice = 0
        valEpCTSens = 0
        valEpCTSpec = 0

        valEpCoreDice = 0
        valEpCoreSens = 0
        valEpCoreSpec = 0

        valEpEnDice = 0
        valEpEnSens = 0
        valEpEnSpec = 0

        valEpPatsNum = 0
        valTime = 0
        epValTime = time.time()
        message = 'Validation'
        logger.info(logMessage(':', message))

        for patIdx, patientDir in enumerate(valpatientsDirList):

            patientName = patientDir.split('/')[-1]
            segmentResultDir = os.path.join(subEpOutputDir, patientName)
            os.mkdir(segmentResultDir)

            logger.info('Val {}/{} patient'.format(patIdx + 1, len(valpatientsDirList)))

            # ------------------------------------------------------------------------------------------
            segmentResult, softmaxResult, segmentResultMask, gTArray = segmentWholeBrain(network,
                                                                          patientDir,
                                                                          True,
                                                                          modals,
                                                                          normType,
                                                                          valSampleSize,
                                                                          receptiveField,
                                                                          True,
                                                                          batchSize, 
                                                                          priviousResult)
            # ------------------------------------------------------------------------------------------
            assert gTArray != []

            temArray = (segmentResult == 3).astype(int)
            segmentResult += temArray

            assert np.all(segmentResult != 3)

            crfResult = denseCRF(softmaxResult)

            npArrayList = [segmentResult, crfResult]

            niisegment, niiCRF = npToNii(patientDir, npArrayList)

            # Save segment results for each patient
            nib.save(niisegment, os.path.join(segmentResultDir, 'segmentResult.nii.gz'))
            nib.save(niiCRF, os.path.join(segmentResultDir, 'crfResult.nii.gz'))

            # np.save(os.path.join(segmentResultDir, 'segmentResult.npy'), segmentResult)
            np.save(os.path.join(segmentResultDir, 'gTArray.npy'), gTArray)
            message = 'Saved results of {}'.format(patientName)

            cTDice, cTSens, cTSpeci = voxleWiseMetrics(segmentResult, 
                                                       gTArray, 
                                                       [1, 2, 4])
            coreDice, cTSens, cTSpec = voxleWiseMetrics(segmentResult, 
                                                        gTArray, 
                                                        [1, 2])
            ehDice, ehSens, ehSpec = voxleWiseMetrics(segmentResult, 
                                                      gTArray, 
                                                      [2, 4])
            valEpCTDice += cTDice
            valEpCTSens += cTSens
            valEpCTSpec += cTSpeci

            valEpCoreDice += coreDice
            valEpCoreSens += cTSens
            valEpCoreSpec += cTSpec

            valEpEhDice += ehDice
            valEpEhSens += ehSens
            valEpEhSpec += ehSpec

            valPMessage = 'Patient: {}'.format(patientName)
            valPMessage += ' Core Dice: {}, '.format(coreDice)
            valPMessage += ' Core Sens: {}'.format(cTSens)
            valPMessage += ' Core Spec: {}'.format(cTSpec)
            logger.info(logMessage('-', valPMessage))

            del segmentResult, segmentResultMask, gTArray
            gc.collect()

        valEpPatsNum = len(valpatientsDirList)
        epValTime = time.time() - epValTime
        valTime += epValTime
        # =========================================================================================

           
        # Compute epoch results
        # =============================================================================================
        # Compute epoch training results
        trainEpLoss /= trainEpBatchNum
        trainEpACC /= trainEpBatchNum
        # *********************************************************************************************
        # Compute epoch validation results
        valEpCTDice /= valEpPatsNum
        valEpCTSens /= valEpPatsNum
        valEpCTSpec /= valEpPatsNum

        valEpCoreDice /= valEpPatsNum
        valEpCoreSens /= valEpPatsNum
        valEpCoreSpec /= valEpPatsNum

        valEpEnDice /= valEpPatsNum
        valEpEnSens /= valEpPatsNum
        valEpEnSpec /= valEpPatsNum
        # =============================================================================================

        # Recording for subEpoch row of table
        # =============================================================================================
        epTrainSampleTime = '{:.3}'.format(epTrainSampleTime)
        epTrainTime = '{:.3}'.format(epTrainTime)
        epValTime = '{:.3}'.format(epValTime)
        # ---------------------------------------------------------------------------------------------
        trainEpLoss = '{:.6f}'.format(trainEpLoss)
        trainEpACC = '{:.6f}'.format(trainEpACC)
        # ---------------------------------------------------------------------------------------------
        trainTRowList.append(['-', '-', '-', '-', '-', '-'])
        trainTRowList.append(['',               '',              epTrainSampleTime, 
                              trainEpLoss,      trainEpACC,      epTrainTime])
        trainTRowList.append(['-', '-', '-', '-', '-', '-'])
        # *********************************************************************************************
        valEpCTDice = '{:.4f}'.format(valEpCTDice)
        valEpCTSens = '{:.4f}'.format(valEpCTSens)
        valEpCTSpec = '{:.4f}'.format(valEpCTSpec)

        valEpCoreDice = '{:.4f}'.format(valEpCoreDice)
        valEpCoreSens = '{:.4f}'.format(valEpCoreSens)
        valEpCoreSpec = '{:.4f}'.format(valEpCoreSpec)

        valEpEnDice = '{:.4f}'.format(valEpEnDice)
        valEpEnSens = '{:.4f}'.format(valEpEnSens)
        valEpEnSpec = '{:.4f}'.format(valEpEnSpec)
        # ---------------------------------------------------------------------------------------------
        valTRowList.append(['-', '-', '-', '-', '-', '-', '-', '-', '-', '-', '-'])
        valTRowList.append([epIdx + 1,        epValTime, 
                            valEpCTDice,      valEpCTSens,       valEpCTSpec, 
                            valEpCoreDice,    valEpCoreSens,     valEpCoreSpec, 
                            valEpEnDice,      valEpEnSens,       valEpEnSpec])
        valTRowList.append(['-', '-', '-', '-', '-', '-', '-', '-', '-', '-', '-'])
        # =============================================================================================
        
        # Epoch logger
        # =============================================================================================
        message = 'Epoch: {}/{} '.format(epIdx + 1, numOfEpochs)
        message += ' Train Loss: {}, '.format(trainEpLoss)
        message += ' Train ACC: {}'.format(trainEpACC)
        logger.info(logMessage('+', message))
        message = 'Epoch: {}/{} '.format(epIdx + 1, numOfEpochs)
        message += ' Val Core Dice: {}, '.format(valEpCoreDice)
        message += ' Val Core Sens: {}'.format(valEpEnSens)
        message += ' Val Core Spec: {}'.format(valEpEnSpec)
        logger.info(logMessage('+', message))
        # =============================================================================================

        # Store network weights
        # =============================================================================================
        weightsFileName = '{}_{}'.format(epIdx, subEpIdx)
        network.saveWeights(weightsFileName)
        # =============================================================================================

        # Reset learning rate
        # =============================================================================================
        oldLeraningRate = network.learningRate.get_value()
        newLearningRate = oldLeraningRate * network.learningRateDecay
        network.learningRate.set_value(newLearningRate)
        message = 'Reset Learning Rate, From {} to {}'.format(oldLeraningRate, newLearningRate)
        logger.info(logMessage('~', message))
        # =============================================================================================

    # #################################################################################################

    # Logger table
    # =================================================================================================
    message = 'The Training Results'
    logger.info(logMessage('=', message))
    logger.info(logTable(trainTRowList))
    logger.info(logMessage('=', '*'))
    # *************************************************************************************************
    message = 'The Validation Results'
    logger.info(logMessage('=', message))
    logger.info(logTable(valTRowList))
    logger.info(logMessage('=', '*'))
    message = 'End Training Loops'
    logger.info(logMessage('#', message))
    # =================================================================================================

    return trainTRowList, valTRowList



def testNetwork(network, configFile):

    logger = logging.getLogger(__name__)

    message = 'Testing {}'.format(network.networkType)
    logger.info(logMessage('#', message))

    # Get config information
    # =================================================================================================
    configInfo = {}
    execfile(configFile, configInfo)
    # =================================================================================================

    # Network summary
    # =================================================================================================
    # Read network summary
    testSampleSize = configInfo['testSampleSize']
    networkType = network.networkType
    receptiveField = network.receptiveField
    networkSummary = network.summary(testSampleSize)
    # -------------------------------------------------------------------------------------------------
    # Logger network summary
    message = 'Network Summary'
    logger.info(logMessage('*', message))
    logger.info(logTable(networkSummary))

    tableRowList = []
    tableRowList.append(['-', '-'])
    tableRowList.append(['Network Type', networkType])
    tableRowList.append(['Receptive Field', receptiveField])
    tableRowList.append(['-', '-'])
    logger.info(logTable(tableRowList))
    logger.info(logMessage('*', '*'))
    # =================================================================================================

    # Test data summary
    # =================================================================================================
    message = 'Test Data Summary'
    logger.info(logMessage('*', message))

    testImageFolder = configInfo['testImageFolder']
    useROITest = configInfo['useROITest']
    modals = configInfo['modals']
    normType = configInfo['normType']
    label = configInfo['useLabel']
    numOfPatients = sum([len(os.listdir(os.path.join(testImageFolder, grade))) 
                         for grade in os.listdir(testImageFolder)])
    # -------------------------------------------------------------------------------------------------
    # Logger test data summary
    tableRowList = []
    tableRowList.append(['Test Image Folder', testImageFolder])
    tableRowList.append(['Number of Patients', numOfPatients])
    tableRowList.append(['Use ROI To Test Network', useROITest])
    tableRowList.append(['Modals', modals])
    tableRowList.append(['Normalization Type in Test Process', normType])
    tableRowList.append(['Using Label', label])

    logger.info(logTable(tableRowList))    
    logger.info(logMessage('*', '*'))
    # =================================================================================================

    # Test setting summary
    # =================================================================================================
    message = 'Test Setting Summary'
    logger.info(logMessage('*', message))
    testSampleSize = configInfo['testSampleSize']
    batchSize = configInfo['batchSize']
    priviousResult = configInfo['priviousResult']
    testResultDir = network.testResultDir
    if priviousResult != '': testResultDir = network.testResultDir2
    # -------------------------------------------------------------------------------------------------
    # Logger test setting summary
    tableRowList = []    
    tableRowList.append(['Test Samples Size', testSampleSize])
    tableRowList.append(['Test Batch Size', batchSize])
    tableRowList.append(['Folder to Store Test Results', testResultDir])

    logger.info(logTable(tableRowList))    
    logger.info(logMessage('*', '*'))
    # =================================================================================================

   
    # Test
    # =================================================================================================
    if label: 
        testRowList = []
        testRowList.append(['-', '-', '-', '-'])
        testRowList.append(['Case ID', 'CTDice', 'CoreDice', 'EhDice'])
        testRowList.append(['-', '-', '-', '-'])

    for modal in os.listdir(testImageFolder):
        modalImageFolder = os.path.join(testImageFolder, modal)
        for patient in os.listdir(modalImageFolder):

            patientDir = os.path.join(modalImageFolder, patient)
            # ---------------------------------------------------------------------------------------------
            # Sample test data
            # For short statement.
            segmentResult, softmaxResult, segmentResultMask, gTArray = segmentWholeBrain(network,
                                                                          patientDir,
                                                                          useROITest,
                                                                          modals,
                                                                          normType,
                                                                          testSampleSize,
                                                                          receptiveField,
                                                                          label,
                                                                          batchSize, 
                                                                          priviousResult)

            if not label: assert gTArray == []

            # ---------------------------------------------------------------------------------------------
            if label:

                cTDice, cTSens, cTSpeci = voxleWiseMetrics(segmentResult, 
                                                           gTArray, 
                                                           [1, 2, 4])
                coreDice, cTSens, cTSpec = voxleWiseMetrics(segmentResult, 
                                                            gTArray, 
                                                            [1, 2])
                ehDice, ehSens, ehSpec = voxleWiseMetrics(segmentResult, 
                                                          gTArray, 
                                                          [2, 4])
                testRowList.append([patient, cTDice, coreDice, ehDice])
            # ---------------------------------------------------------------------------------------------
            crfResult = denseCRF(softmaxResult)

            npArrayList = [segmentResult, crfResult]

            niiSegment, niiCRF = npToNii(patientDir, npArrayList)

            # Save segment results for each patient
            nib.save(niiSegment, os.path.join(testResultDir, '{}.nii.gz'.format(patient)))
            # nib.save(niiCRF, os.path.join(testResultDir, 'crfResult.nii.gz'))
            # np.save(os.path.join(testResultDir, 'result.npy'), segmentResult)
            # np.save(os.path.join(testResultDir, 'resultMask.npy'), segmentResultMask)
            message = 'Saved results of {}'.format(patient)
            logger.info(logMessage('-', message))

    if label:
        testRowList.append(['-', '-', '-', '-'])
        logger.info(logTable(testRowList))
    # =================================================================================================




def segmentWholeBrain(network,
                      patientDir,
                      useROI,
                      modals,
                      normType,
                      sampleSize,
                      receptiveField,
                      label,
                      batchSize, 
                      priviousResult):

    logger = logging.getLogger(__name__)
    # ---------------------------------------------------------------------------------------------
    # Sample test data
    # For short statement.
    sampleWholeImageResult = sampleWholeBrain(patientDir, 
                                              normType, 
                                              modals, 
                                              sampleSize, 
                                              receptiveField,
                                              label, 
                                              useROI, 
                                              priviousResult)

    samplesOfWholeImage = sampleWholeImageResult[0]
    labelsOfWholeImage = sampleWholeImageResult[1]
    wholeLabelCoordList = sampleWholeImageResult[2]
    imageShape = sampleWholeImageResult[3]
    gTArray = sampleWholeImageResult[4]
    assert gTArray != [] if label else gTArray == [], (label, gTArray)
    # ---------------------------------------------------------------------------------------------
    # Prepare ndarray to record segment results for each patient
    segmentResult = np.zeros(imageShape, dtype = 'int32')
    softmaxResult = np.zeros([4] + imageShape, dtype = 'int32')
    segmentResultMask = np.zeros(imageShape, dtype = 'int16')
    patient = patientDir.split('/')[-1]
    assert patient.startswith('Brats'), patient
    # ---------------------------------------------------------------------------------------------
    # Prepare for test batch loop
    numOfSamples = len(wholeLabelCoordList)
    batchIdxList = [batchIdx for batchIdx 
                    in xrange(0, numOfSamples, batchSize)]

    # For the last batch not to be too small.
    batchIdxList[-1] = numOfSamples
    batchNum = len(batchIdxList[:-1])
    logger.info('Segment the volumes need {} batchs'.format(batchNum))
    assert len(batchIdxList) > 1

    if label: testBatchACCList = []
    # ---------------------------------------------------------------------------------------------
    # Test batch loop
    for batchIdx in xrange(batchNum):

        # For showing progress
        if batchIdx % 100 == 0:
            logger.info('Batch {}/{}'.format(batchIdx + 1, batchNum))

        if label: testBatchACC = 0

        startIdx = batchIdxList[batchIdx]
        endIdx = batchIdxList[batchIdx + 1]

        samplesBatch = samplesOfWholeImage[startIdx:endIdx]
        samplesBatch = np.asarray(samplesBatch, dtype = theano.config.floatX)

        labelsBatch = labelsOfWholeImage[startIdx:endIdx]
        labelsBatch = np.asarray(labelsBatch, dtype = 'int32')

        testPredictionLabel, testPrediction = network.testFunction(samplesBatch)

        assert isinstance(testPredictionLabel, np.ndarray)
        labelZ = sampleSize[0] - receptiveField + 1
        labelX = sampleSize[1] - receptiveField + 1
        labelY = sampleSize[2] - receptiveField + 1

        assert testPredictionLabel.shape[0] == (endIdx - startIdx) * labelZ * labelY * labelX
        testPredictionLabel = np.reshape(testPredictionLabel, 
                                        ((endIdx - startIdx), labelZ, labelX, labelY))
        # For simplify the change, just set the class = 4
        testPrediction = np.reshape(testPrediction, ((endIdx - startIdx), labelZ, labelX, labelY, 4))
        testPrediction = np.transpose(testPrediction, (0, 4, 1, 2, 3))
        assert testPredictionLabel.shape == ((endIdx - startIdx), labelZ, labelX, labelY)
        assert testPrediction.shape == ((endIdx - startIdx), 4, labelZ, labelX, labelY)
        # ----------------------------------------------------------------------------------------
        # Store results of each batch
        for idx, labels in enumerate(testPredictionLabel):
            softLabels = testPrediction[idx]
            assert batchIdx * batchSize == batchIdxList[batchIdx]

            labelCoordIdx = batchIdx * batchSize + idx
            labelCoord = wholeLabelCoordList[labelCoordIdx]
            zL = labelCoord[0][0]
            zR = labelCoord[0][1]
            xL = labelCoord[1][0]
            xR = labelCoord[1][1]
            yL = labelCoord[2][0]
            yR = labelCoord[2][1]
            assert len(set([zR - zL, xR - xL, yR - yL])) == 1
            segmentResult[zL:zR, xL:xR, yL:yR] = labels
            softmaxResult[:, zL:zR, xL:xR, yL:yR] = softLabels
            segmentResultMask[zL:zR, xL:xR, yL:yR] += np.ones(labels.shape, dtype = 'int16')

            if label:
                rightPreLocArray = (gTArray[zL:zR, xL:xR, yL:yR] == labels).astype(int)
                testBatchACC += np.mean(rightPreLocArray)

        if label: 
            testBatchACCList.append(testBatchACC / (endIdx - startIdx))
            logger.debug('Test Batch {} | Test ACC {}'.format(batchIdx, testBatchACCList[-1]))

    assert np.any(segmentResult)
    assert np.any(softmaxResult)
    # ---------------------------------------------------------------------------------------------
    temSegArray = (segmentResult == 3).astype(int)
    segmentResult += temSegArray
    assert np.all(segmentResult != 3)

    if label:
        temGtArray = (gTArray == 3).astype(int)
        gTArray += temGtArray
        assert np.all(gTArray != 3)
    # ---------------------------------------------------------------------------------------------

    return segmentResult, softmaxResult, segmentResultMask, gTArray




def npToNii(patientDir, npList):

    niiList = []

    modalFile = os.listdir(patientDir)[0]
    modalFile = os.path.join(patientDir, modalFile)

    image = nib.load(modalFile)

    for npArray in npList:
        niimage = nib.Nifti1Image(npArray, image.affine)
        niimage.set_data_dtype('int16')

        niiList.append(niimage)

    return niiList



import pydensecrf.densecrf as dcrf
from pydensecrf.utils import create_pairwise_gaussian, create_pairwise_bilateral, unary_from_softmax



def denseCRF(softmaxResult):

    nClass, shape = softmaxResult.shape[0], softmaxResult.shape[1:]
    crfResult = np.empty(shape)

    d = dcrf.DenseCRF(np.prod(shape), nClass)
    U = unary_from_softmax(softmaxResult)

    d.setUnaryEnergy(U)
    feats = create_pairwise_gaussian(sdims = (1.0, 1.0, 1.0), shape = shape)
    d.addPairwiseEnergy(feats, compat=3, kernel=dcrf.FULL_KERNEL, normalization=dcrf.NORMALIZE_SYMMETRIC)
    Q = d.inference(5) 
    crfResult = np.argmax(Q, axis=0).reshape(shape)

    return crfResult



