#!/usr/bin/env python3.7

# (C) Copyright 2019 UCAR
#
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.

"""

Tool to obtain ensemble restarts from archive.

User provides a date range, the number of cycles and a random seed. If number of cycles is set
to 0 then a list of dates will be read from a file called datetimes_to_process.txt. This should be
formated as e.g.:
2019061200
2019061300
2019061406
etc

Looping over number of cycles the algorithm is:

1. Get all ensemble members for the cycle.
2. Untar the data
3. Convert to B matrix variables, psi chi etc using a parallel job.
4. Check for sucessful conversion.
5. Remove the original data

"""


# External libradasries
# ------------------

import numpy as np
import os
import datetime
import argparse
import random

import ConvertEnsemble.modules.model_utils as mu
import ConvertEnsemble.modules.fv3model as fv3model

# User input
# ----------

sargs=argparse.ArgumentParser()
sargs.add_argument( "-f", "--readdatetimes", default='0')
sargs.add_argument( "-s", "--start",         default='2019061200')  # yyyymmddHH
sargs.add_argument( "-e", "--end",           default='2019101506')  # yyyymmddHH
sargs.add_argument( "-q", "--freq",          default='6')           # Hours
sargs.add_argument( "-n", "--ncycs",         default='100')
sargs.add_argument( "-r", "--rseed",         default='1')
sargs.add_argument( "-m", "--model",         default='gfs')
sargs.add_argument( "-j", "--jedi_build",    default='/scratch1/NCEPDEV/da/Daniel.Holdaway/JediDev/fv3-bundle-dev/build-intel-17.0.5.239-release-default')
sargs.add_argument( "-w", "--work_dir",      default='')


args    = sargs.parse_args()
readdts = int(args.readdatetimes)==1
start   = args.start
final   = args.end
freq    = int(args.freq)
ncycs   = int(args.ncycs)
rseed   = int(args.rseed)
model   = args.model
jbuild  = args.jedi_build
wrkdir  = args.work_dir

if wrkdir == '':
  wdir = os.getcwd()
else:
  wdir = wrkdir

print("\n Ensemble processing for Static B ... \n")
if (readdts):
  print(" Will read date times to process from datetimes_to_process.txt")
else:
  print(" Not reading from file will geneate processing dates from the following: ")
  print("  - Start datetime: "+start)
  print("  - Final datetime: "+final)
  print("  - Frequency of cycles: "+str(freq))
  print("  - Number cycles:  "+str(ncycs))
  print("  - Random seed:    "+str(rseed))

print("  - Model being used is "+model)
print("  - JEDI build path: "+jbuild)
print("  - Working directory: "+wdir)

print("\n")


# Construct class with model specific methods
# -------------------------------------------
fv3model = fv3model.factory.create(model.upper())


# Set up list of dates to process
# -------------------------------

if (readdts):

  with open('datetimes_to_process.txt', 'r') as fh:
    datetimes_str = fh.readlines()

  ncycs = len(datetimes_str)
  tmp = datetimes_str[0]
  start = tmp[0:10]
  tmp = datetimes_str[ncycs-1]
  final = tmp[0:10]
  freq = 0
  rseed = -1

  datetimes = np.empty([ncycs], dtype = datetime.datetime)

  for n in range(ncycs):
    tmp = str(datetimes_str[n])
    datetimes[n] = datetime.datetime.strptime(tmp[0:10], mu.dtformat)

else:

  # Set datetime and delta objects based on total range
  datetime_start = datetime.datetime.strptime(start, mu.dtformat)
  datetime_final = datetime.datetime.strptime(final, mu.dtformat)
  totaldelta = datetime_final-datetime_start
  totalhour = totaldelta.total_seconds()/3600

  # Check user provided sensible frequency
  resi = totalhour/freq - float(int(totalhour/freq))
  if (resi != 0.0):
    print(" ABORT: (final-start)/freq is not a whole number")
    exit()

  # Total number of cyles
  ntcycs = int(totalhour / freq) + 1

  # Array to sample from
  tdatetimes = np.array([datetime_start + datetime.timedelta(hours=6*i) for i in range(ntcycs)])

  # Check that number of cycles user wants is compatible with provided range
  if (ntcycs < ncycs):
    print(" WARNING: total date range does not contain enough cycles for input choice, "
            "reducing to every datetime in the range.")
    ncycs = ntcycs

  # Non replacement random sample of size ncycs
  random.seed(rseed)
  datetimes_index = np.sort(random.sample(range(ntcycs), ncycs))

  # Fill up array of datetimes using random selection
  datetimes = np.empty([ncycs], dtype = datetime.datetime)
  for n in range(ncycs):
    datetimes[n] = tdatetimes[datetimes_index[n]]


# Write the datetimes being processed to file
# -------------------------------------------
with open('datetimes_processed.txt', 'w') as fh:
  for item in datetimes:
    fh.write("%s\n" % item.strftime(mu.dtformat))


# Loop over cycles and process the ensemble
# -----------------------------------------

for n in range(1): #range(ncycs):

  # Datetime and directories for this cycle
  fv3model.cycleTime(datetimes[n])
  fv3model.setDirectories(wdir)

  if os.path.exists(fv3model.workDir+'/AllDone'):
    print(" This cycle is done, skipping ...")
    os.remove(fv3model.workDir+'/working')
    continue

  # Convert each member
  if not os.path.exists(fv3model.workDir+'/'+fv3model.HeraCopyDone):
    fv3model.membersFromHera()
  else:
    print(" membersFromHera already complete \n")

  # Extract member
  if not os.path.exists(fv3model.workDir+'/'+fv3model.HeraExtrDone):
    fv3model.extractConvertedMembers()
  else:
    print(" extractConvertedMembers already complete \n")

  # Prepare yaml file for converting the members
  fv3model.prepareConvertDirsYamls()

  # Convert the ensemble members to psi/chi
  if not os.path.exists(os.path.join(fv3model.workDir,fv3model.ConvertDone)):
    fv3model.convertMembersUnbalanced(jbuild)
  else:
    print(" convertMembersUnbalanced already complete \n")

  # Tar up members
  if not os.path.exists(os.path.join(fv3model.workDir,fv3model.tarUpMembersDone)):
    fv3model.tarUpMembers()
  else:
    print(" tarUpAndShipS3 already complete \n")

  # Ship to S3
  if not os.path.exists(os.path.join(fv3model.workDir,fv3model.Ship2S3Done)):
    fv3model.Ship2S3()
  else:
    print(" Ship2S3 already complete \n")

  # All done
  fv3model.allDone()

exit()








exit()