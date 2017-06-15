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

from utils.sampling import getSamplesForSubEpoch, sampleWholeImage
from utils.loadData import loadSinglePatientData
from utils.general import logMessage, logTable
from models.sectorNet import SectorNet
from models.baseNet import BaseNet





def generateNetwork(configFile):

    logger = logging.getLogger(__name__)

    # Get config infomation
    configInfo = {}
    execfile(configFile, configInfo)

    # Choose the network type
    # ====================================================================================
    # The networksDict should conresponding to the import statement. 
    networksDict = {'sectorNet': SectorNet,
                    'baseNet': BaseNet}

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
    network = networkClass(configFile)
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
    networkType = network.networkType
    receptiveField = network.receptiveField
    networkSummary = network.summary(trainSampleSize)
    # ------------------------------------------------------------------------------
    # Logger network summary
    message = 'Network Summary'
    logger.info(logMessage('*', message))
    logger.info(networkSummary)
    logger.info(logMessage('-', '-'))
    tableRowList = []
    tableRowList.append(['-', '-'])
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
    imageGrades = configInfo['imageGrades']
    numOfPatients = configInfo['numOfPatients']
    modals = configInfo['modals']
    useROI = configInfo['useROI']
    normType = configInfo['normType']
    weightMapType = configInfo['weightMapType']
    # ----------------------------------------------------------------------------
    # Logger training and validation data information
    message = 'Training and Validation Data Summary'
    logger.info(logMessage('*', message))

    tableRowList = []
    tableRowList.append(['-', '-'])
    tableRowList.append(['Image Folder', imageFolder])
    tableRowList.append(['Image Grades', imageGrades])
    tableRowList.append(['Number of Patients', numOfPatients])
    tableRowList.append(['Modals', modals])
    tableRowList.append(['Use ROI', useROI])
    tableRowList.append(['Normalization Type', normType])
    tableRowList.append(['Weight Map Type', weightMapType])
    tableRowList.append(['-', '-'])

    logger.info(logTable(tableRowList))
    logger.info(logMessage('*', '*'))
    # ===========================================================================

    # Training and validation setting infomation
    # ===========================================================================
    # Read training and validation setting information
    trainValRatio = configInfo['trainValRatio']
    memoryThreshold = configInfo['memoryThreshold']
    usePoolToSample = configInfo['usePoolToSample']
    numOfEpochs = configInfo['numOfEpochs']
    numOfSubEpochs = configInfo['numOfSubEpochs']
    batchSize = configInfo['batchSize']
    trainSampleSize = configInfo['trainSampleSize']
    valSampleSize = configInfo['valSampleSize']
    numOfTrainSamplesPerSubEpoch = configInfo['numOfTrainSamplesPerSubEpoch']
    numOfValSamplesPerSubEpoch = int(float(numOfTrainSamplesPerSubEpoch) / trainValRatio)
    weightsFolder = configInfo['weightsFolder']
    assert batchSize < numOfTrainSamplesPerSubEpoch
    assert batchSize < numOfValSamplesPerSubEpoch
    # ---------------------------------------------------------------------------
    # Logger training and validation setting infomation
    message = 'Training and Validation setting Summary'
    logger.info(logMessage('*', message))

    tableRowList = []
    tableRowList.append(['-', '-'])
    tableRowList.append(['Training / validation', trainValRatio])
    tableRowList.append(['Memory Threshold for Subepoch', '{}G'.format(memoryThreshold)])
    tableRowList.append(['Wheather Use MultiProcess to Sample', usePoolToSample])
    tableRowList.append(['Number of Epochs', numOfEpochs])
    tableRowList.append(['Number of Subepochs', numOfSubEpochs])
    tableRowList.append(['Batch Size', batchSize])
    tableRowList.append(['Training Samples Size', trainSampleSize])
    tableRowList.append(['Validation Samples Size', valSampleSize])
    tableRowList.append(['Number of Training Samples for Subepoch', 
                         numOfTrainSamplesPerSubEpoch])
    tableRowList.append(['Number of Validation Samples for Subepoch', 
                         numOfValSamplesPerSubEpoch])
    tableRowList.append(['Folder to Store Weights During Training', weightsFolder])
    tableRowList.append(['-', '-'])

    logger.info(logTable(tableRowList))
    logger.info(logMessage('*', '*'))
    # ===========================================================================

    # Prepare patients file dir list
    # ===========================================================================
    # Read patients dir list
    patientsDirList = []
    gradeDirList = [os.path.join(imageFolder, grade) for grade in imageGrades]
    for gradeDir in gradeDirList:
        patientsDirList += [os.path.join(gradeDir, patient) 
                            for patient in os.listdir(gradeDir)]

    # Make sure there are no same elements in the patientsDirList
    assert len(patientsDirList) == len(set(patientsDirList))
    random.shuffle(patientsDirList)
    # ---------------------------------------------------------------------------
    # Divide patients dir in two part according to trainValRatio
    patsDirForValList = patientsDirList[::trainValRatio + 1]
    patsDirForTrainList = [patsDir for patsDir in patientsDirList 
                           if patsDir not in patsDirForValList]
    assert len(patsDirForValList) + len(patsDirForTrainList) == len(patientsDirList)

    message = 'We get {} patients files. '.format(len(patientsDirList))
    message += 'Randomly choose {} for training '.format(len(patsDirForTrainList))
    message += 'and {} for validation'.format(len(patsDirForValList))
    logger.info(logMessage(' ', message))
    # ---------------------------------------------------------------------------
    # Prepare training patients dir list for each subepoch, because the 
    # training data may be so large and need to be split for each subepoch
    numOfModals = len(modals)
    memoryNeededPerPatData = 0.035 * numOfModals + int(useROI) * 0.020
    # memortThreshold should large than a single patient need memory
    assert memoryThreshold > memoryNeededPerPatData

    maxPatNumPerSubEpoch = math.floor(memoryThreshold / memoryNeededPerPatData)
    maxPatNumPerSubEpoch = int(maxPatNumPerSubEpoch)
    patDirPerSubEpochDict = {}
    # If len(patsDirForTrainList) < maxPatNumPerSubEpoch, 
    # each will use same patients dir
    for subEpIdx in xrange(numOfSubEpochs):
        chosenPatsDir = patsDirForTrainList[:maxPatNumPerSubEpoch]
        patDirPerSubEpochDict[subEpIdx] = chosenPatsDir
        random.shuffle(patsDirForTrainList)
    # ===========================================================================

    # Prepare a table to record and show training and validation results
    # ===========================================================================
    tableRowList = []
    tableRowList.append(['-', '-', '-', '-', '-', '-', '-', '-', '-'])
    tableRowList.append(['EPOCH',      'SUBEPOCH',    'Sampling Time', 
                         'Train Loss', 'Train ACC',   'Train Time', 
                         'Val Loss',   'Val ACC',     'Val Time'])
    tableRowList.append(['-', '-', '-', '-', '-', '-', '-', '-', '-'])
    # ===========================================================================

    # Prepare folder to store network weights during training
    # ===========================================================================
    storeTime = time.strftime('%y-%m-%d_%H:%m:%S')
    weightsDir = os.path.join(weightsFolder, str(storeTime))
    os.mkdir(weightsDir)
    # ===========================================================================

    # Train and Val
    # ##################################################################################################
    for epIdx in xrange(numOfEpochs):

        message = 'EPOCH: {}/{}'.format(epIdx + 1, numOfEpochs)
        logger.info(logMessage('+', message))

        # Initial some epoch recordor
        # ==============================================================================================
        trainEpLoss = 0
        trainEpACC = 0
        trainEpBatchNum = 0
        # **********************************************************************************************
        valEpLoss = 0
        valEpACC = 0
        valEpBatchNum = 0
        # **********************************************************************************************
        epSampleTime = 0
        epTrainTime = 0
        epValTime = 0
        # ==============================================================================================

        for subEpIdx in xrange(numOfSubEpochs):

            message = 'SUBEPOCH: {}/{}'.format(subEpIdx + 1, numOfSubEpochs)
            logger.info(logMessage('-', message))

            # Training
            # ==========================================================================================
            # Sample training data
            sampleTime = time.time()
            message = 'Sampling Training Data'
            logger.info(logMessage('-', message))
            trainSampleAndLabelList = getSamplesForSubEpoch(numOfTrainSamplesPerSubEpoch,
                                                       patDirPerSubEpochDict[subEpIdx],
                                                       useROI,
                                                       modals,
                                                       normType,
                                                       trainSampleSize ,
                                                       receptiveField,
                                                       weightMapType,
                                                       usePoolToSample)

            trainSamplesList, trainLabelsList = trainSampleAndLabelList
            sampleTime = time.time() - sampleTime
            epSampleTime += sampleTime
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
            trainTime = time.time() - trainTime
            epTrainTime += trainTime
            # ........................................................................................
            # Release source
            del trainSamplesList[:], trainLabelsList[:]
            del trainSamplesList, trainLabelsList
            del trainSamplesBatch, trainLabelsBatch
            gc.collect()
            # ========================================================================================

            # Validation
            # ========================================================================================
            # Sample validatation data
            message = 'Sampling Validation Data'
            logger.info(logMessage('-', message))
            valSampleAndLabelList = getSamplesForSubEpoch(numOfValSamplesPerSubEpoch,
                                                          patsDirForValList,
                                                          useROI,
                                                          modals,
                                                          normType,
                                                          valSampleSize ,
                                                          receptiveField,
                                                          weightMapType,
                                                          usePoolToSample)

            valSamplesList, valLabelsList = valSampleAndLabelList
            sampleTime += time.time() - trainTime 
            epSampleTime += sampleTime
            # ---------------------------------------------------------------------------------------
            # Prepare for val batch loop
            valBatchIdxList = [valBatchIdx for valBatchIdx 
                               in xrange(0, numOfValSamplesPerSubEpoch, batchSize)]

            # For the last batch not to be too small.
            valBatchIdxList[-1] = numOfValSamplesPerSubEpoch

            assert len(valBatchIdxList) > 1
            valBatchNum = len(valBatchIdxList[:-1])
            # ---------------------------------------------------------------------------------------
            # Validation batch loop
            valSubEpLoss = 0
            valSubEpACC = 0
            valSubEpBatchNum = 0
            valTime = time.time()
            message = 'Validation'
            logger.info(logMessage(':', message))
            # .......................................................................................
            for valBatchIdx in xrange(valBatchNum):
                # Just for calear.
                valStartIdx = valBatchIdxList[valBatchIdx]
                valEndIdex = valBatchIdxList[valBatchIdx + 1]

                valSamplesBatch = valSamplesList[valStartIdx:valEndIdex]
                valSamplesBatch = np.asarray(valSamplesBatch, dtype = theano.config.floatX)

                valLabelsBatch = valLabelsList[valStartIdx:valEndIdex]
                valLabelsBatch = np.asarray(valLabelsBatch, dtype = 'int32')

                valBatchLoss, valBatchAcc = network.valFunction(valSamplesBatch, valLabelsBatch)
                # Record subepoch validation results.
                valSubEpLoss += valBatchLoss
                valSubEpACC += valBatchAcc
                valSubEpBatchNum += 1
            valTime = time.time() - valTime
            epValTime += valTime
            # .........................................................................................
            # Release source
            del valSamplesList[:], valLabelsList[:]
            del valSamplesList, valLabelsList
            del valSamplesBatch, valLabelsBatch
            gc.collect()
            # =========================================================================================

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
            # Record epooch validation results and computer validation subepoch results
            # -----------------------------------------------------------------------------------------
            # Record validation epoch results
            valEpLoss += valSubEpLoss
            valEpACC += valSubEpACC
            valEpBatchNum += valSubEpBatchNum
            # -----------------------------------------------------------------------------------------
            # Compute validation subepoch results
            valSubEpLoss /= valSubEpBatchNum
            valSubEpACC /= valSubEpBatchNum
            # =========================================================================================

            # Recording for subEpoch row of table
            # =========================================================================================
            indexColumn = epIdx + 1 if subEpIdx == 0 else ''
            sampleTime = '{:.3}'.format(sampleTime)
            trainTime = '{:.3}'.format(trainTime)
            valTime = '{:.3}'.format(valTime)

            trainSubEpLoss = '{:.6f}'.format(trainSubEpLoss)
            trainSubEpACC = '{:.6f}'.format(trainSubEpACC)
            valSubEpLoss = '{:.6f}'.format(valSubEpLoss)
            valSubEpACC = '{:.6f}'.format(valSubEpACC)

            tableRowList.append([indexColumn,      subEpIdx + 1,      sampleTime,
                                 trainSubEpLoss,   trainSubEpACC,     trainTime,
                                 valSubEpLoss,     valSubEpACC,       valTime])
            # =========================================================================================

            # Subepoch logger
            # =========================================================================================
            message = 'Subepoch: {}/{} '.format(subEpIdx + 1, numOfSubEpochs)
            message += ' Train Loss: {}, '.format(trainSubEpLoss)
            message += ' Train ACC: {}'.format(trainSubEpACC)
            logger.info(logMessage('-', message))
            message = 'Subepoch: {}/{} '.format(subEpIdx + 1, numOfSubEpochs)
            message += ' Val Loss: {}, '.format(valSubEpLoss)
            message += ' Val ACC: {}'.format(valSubEpACC)
            logger.info(logMessage('-', message))
            # =========================================================================================
           
        # Compute epoch results
        # =============================================================================================
        # Compute epoch training results
        trainEpLoss /= trainEpBatchNum
        trainEpACC /= trainEpBatchNum
        # *********************************************************************************************
        # Compute epoch validation results
        valEpLoss /= valEpBatchNum
        valEpACC /= valEpBatchNum
        # =============================================================================================

        # Recording for subEpoch row of table
        # =============================================================================================
        epSampleTime = '{:.3}'.format(epSampleTime)
        epTrainTime = '{:.3}'.format(epTrainTime)
        epValTime = '{:.3}'.format(epValTime)

        trainEpLoss = '{:.6f}'.format(trainEpLoss)
        trainEpACC = '{:.6f}'.format(trainEpACC)
        valEpLoss = '{:.6f}'.format(valEpLoss)
        valEpACC = '{:.6f}'.format(valEpACC)

        tableRowList.append(['-', '-', '-', '-', '-', '-', '-', '-', '-'])
        tableRowList.append(['',               '',              epSampleTime, 
                             trainEpLoss,      trainEpACC,      epTrainTime, 
                             valEpLoss,        valEpACC,        epValTime])
        tableRowList.append(['-', '-', '-', '-', '-', '-', '-', '-', '-'])
        # =============================================================================================
        
        # Epoch logger
        # =============================================================================================
        message = 'Epoch: {}/{} '.format(epIdx + 1, numOfEpochs)
        message += ' Train Loss: {}, '.format(trainEpLoss)
        message += ' Train ACC: {}'.format(trainEpACC)
        logger.info(logMessage('+', message))
        message = 'Epoch: {}/{} '.format(epIdx + 1, numOfEpochs)
        message += ' Val Loss: {}, '.format(valEpLoss)
        message += ' Val ACC: {}'.format(valEpACC)
        logger.info(logMessage('+', message))
        # =============================================================================================

        # Store network weights
        # =============================================================================================
        weightsFileName = '{}_{}'.format(epIdx, subEpIdx)
        weightsFileNameWithPath = os.path.join(weightsDir, weightsFileName)
        network.saveWeights(weightsFileNameWithPath)
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
    logger.info(logTable(tableRowList))
    logger.info(logMessage('=', '='))
    message = 'End Training Loops'
    logger.info(logMessage('#', message))
    # =================================================================================================

    return tableRowList



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
    logger.info(networkSummary)

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
    useTestData = configInfo['useTestData']
    numOfPatients = len(os.listdir(testImageFolder))
    # -------------------------------------------------------------------------------------------------
    # Logger test data summary
    tableRowList = []
    tableRowList.append(['Test Image Folder', testImageFolder])
    tableRowList.append(['Number of Patients', numOfPatients])
    tableRowList.append(['Use ROI To Test Network', useROITest])
    tableRowList.append(['Modals', modals])
    tableRowList.append(['Normalization Type in Test Process', normType])
    tableRowList.append(['Using Test Data', useTestData])

    logger.info(logTable(tableRowList))    
    logger.info(logMessage('*', '*'))
    # =================================================================================================

    # Test setting summary
    # =================================================================================================
    message = 'Test Setting Summary'
    logger.info(logMessage('*', message))
    testSampleSize = configInfo['testSampleSize']
    batchSize = configInfo['batchSize']
    outputFolder = configInfo['outputFolder']
    # -------------------------------------------------------------------------------------------------
    # Logger test setting summary
    tableRowList = []    
    tableRowList.append(['Test Samples Size', testSampleSize])
    tableRowList.append(['Test Batch Size', batchSize])
    tableRowList.append(['Folder to Store Test Results', outputFolder])

    logger.info(logTable(tableRowList))    
    logger.info(logMessage('*', '*'))
    # =================================================================================================

    # Prepare output folder
    # ==========================================================
    storeTime = time.strftime('%y-%m-%d_%H:%m:%S')
    outputDir = os.path.join(outputFolder, str(storeTime))
    os.mkdir(outputDir)
    # =================================================================================================

    # Test
    # =================================================================================================
    for patient in os.listdir(testImageFolder):

        patientDir = os.path.join(testImageFolder, patient)
        # ---------------------------------------------------------------------------------------------
        # Sample test data
        # For short statement.
        sampleWholeImageResult = sampleWholeImage(patientDir, 
                                                  useROITest, 
                                                  modals, 
                                                  normType, 
                                                  testSampleSize, 
                                                  receptiveField,
                                                  useTestData)

        samplesOfWholeImage = sampleWholeImageResult[0]
        labelsOfWholeImage = sampleWholeImageResult[1]
        wholeLabelCoordList = sampleWholeImageResult[2]
        imageShape = sampleWholeImageResult[3]

        # ---------------------------------------------------------------------------------------------
        # Prepare ndarray to record segment results for each patient
        segmentResult = np.zeros(imageShape, dtype = 'int32')
        segmentResultMask = np.zeros(imageShape, dtype = 'int16')
        segmentResultNameWithPath = os.path.join(outputDir, patient)
        # ---------------------------------------------------------------------------------------------
        # Prepare for test batch loop
        numOfSamples = len(wholeLabelCoordList)
        batchIdxList = [batchIdx for batchIdx 
                        in xrange(0, numOfSamples, batchSize)]

        # For the last batch not to be too small.
        batchIdxList[-1] = numOfSamples
        batchNum = len(batchIdxList[:-1])
        assert len(batchIdxList) > 1
        # ---------------------------------------------------------------------------------------------
        # Test batch loop
        for batchIdx in xrange(batchNum):

            startIdx = batchIdxList[batchIdx]
            endIdex = batchIdxList[batchIdx + 1]

            samplesBatch = samplesOfWholeImage[startIdx:endIdex]
            samplesBatch = np.asarray(samplesBatch, dtype = theano.config.floatX)

            labelsBatch = labelsOfWholeImage[startIdx:endIdex]
            labelsBatch = np.asarray(labelsBatch, dtype = 'int32')

            testPredictionLabel = network.testFunction(samplesBatch)
            testPredictionLabel = testPredictionLabel[0]

            assert isinstance(testPredictionLabel, np.ndarray)
            labelZ = testSampleSize[0] - receptiveField + 1
            labelX = testSampleSize[1] - receptiveField + 1
            labelY = testSampleSize[2] - receptiveField + 1
            testPredictionLabel = np.reshape(testPredictionLabel, (batchSize, labelZ, labelX, labelY))
            assert testPredictionLabel.shape == (batchSize, labelZ, labelX, labelY)
            # ----------------------------------------------------------------------------------------
            # Store results of each batch
            for idx, label in enumerate(testPredictionLabel):

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
                segmentResult[zL:zR, xL:xR, yL:yR] = label
                segmentResultMask[zL:zR, xL:xR, yL:yR] += np.ones(label.shape, dtype = 'int16')

        assert not np.any(segmentResult)
        # ---------------------------------------------------------------------------------------------
        # Save segment results for each patient
        message = 'Saved results of {}'.format(patient)
        logger.info(logMessage('-', message))
        np.save(segmentResultNameWithPath + 'result', segmentResult)
        np.save(segmentResultNameWithPath + 'resultMask', segmentResultMask)
    # =================================================================================================






















