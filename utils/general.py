'''
Some short simple and helper function at here.
'''

import os
import logging
import shutil
import numpy as np

def makeDir(dir, force = False):

    '''
    The force parameter is dangerous. Be careful to use it.
    '''

    logger = logging.getLogger(__name__)

    if os.path.exists(dir):
        logger.debug('\nThe dir, {}, has already been here.'.format(dir))

        if force:
            shutil.rmtree(dir)
            logger.debug('\nForce to remove the exist dir, {}'.format(dir))

            os.mkdir(dir)
            logger.debug('\nHave made the new dir, {}, after removing the old one.'.format(dir))

        else:
            logger.debug('\nFailed to create the dir, {}, \
                         because there exist one and force == False'.format(dir))

    else:
        os.mkdir(dir)
        logger.debug('\nSucessfully created the dir, {}'.format(dir))


def numpyArrayCounter(numpyArray):

    unique, counts = np.unique(numpyArray, return_counts = True)

    return np.asarray((unique, counts)).T



def logMessage(sample, message):

    # So, the message should better not long than 80

    message = ' ' + message + ' '
    messageLen = len(message)

    maxLen = 130
    maxLenStr = '{}'.format(maxLen)

    return '\n' + '{:{padSampl}{align}{width}}'.format(message, padSampl = sample, align = '^', width = maxLenStr)
    


def logTable(tableRowList):

    maxLen = 130

    columnNum = len(tableRowList[1])

    verticalLineNum = columnNum - 1

    maxLenPerColumnList = [0] * columnNum

    for row in tableRowList:
        tempColumnLen = [len('{}'.format(column)) for column in row]
        maxLenPerColumnList = [max(tempColumnLen[i], maxLenPerColumnList[i]) 
                               for i in xrange(columnNum)]

    wholeNeedLen = sum(maxLenPerColumnList)
    remainLen = maxLen - wholeNeedLen - verticalLineNum

    assert remainLen >= 0

    columnLenList = maxLenPerColumnList
    lenDistriList = [length / float(wholeNeedLen) for length in columnLenList]

    remainLenDistriList = np.random.choice(columnNum,
                                           size = remainLen,
                                           replace = True,
                                           p = lenDistriList)

    assert len(remainLenDistriList) == remainLen

    for i in remainLenDistriList:
        columnLenList[i] += 1

    assert sum(columnLenList) + verticalLineNum == maxLen

    pattern = '{:^{length}}'
    table = ''

    for i, row in enumerate(tableRowList):
        if all([col == '-' for col in row]):
            row = ['-' * columnLenList[i] for i in xrange(columnNum)]
        for j, column in enumerate(row):
            table += pattern.format(column, length = columnLenList[j])
            if j < columnNum - 1:
                table += '|'
            else:
                table += '\n'

    table = '\n' + table

    return table
