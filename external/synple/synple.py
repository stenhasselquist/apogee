#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""Python wrapper for synspec 

Calculation of synthetic spectra of stars and convolution with a rotational/Gaussian kernel.
Makes the use of synspec simpler, and retains the main functionalities (when used from
python). The command line interface for the shell is even simpler but fairly limited. 

For information on
synspec visit http://nova.astro.umd.edu/Synspec43/synspec.html.

Example
-------

To compute the solar spectrum between 6160 and 6164 angstroms, using a model atmosphere in
the file sun.mod (provided with the distribution), with the output going into the file
sun.syn

   $synple.py sun.mod 6160. 6164. 

To force a micro of 1.1 km/s, and convolve the spectrum with a Gaussian kernel with a fwhm 
of 0.1 angstroms

   $synple.py sun.mod 6160. 6164. 1.1  0.1

To perform the calculations above in python and compare the emergent normalized profiles

   >>> from synple import syn
   >>> x, y, z = syn('sun.mod', (6160.,6164.))
   >>> x2, y2, z2 = syn('sun.mod', (6160.,6164.), vmicro=1.1, fwhm=0.1)

   in plain python
   >>> import matplotlib.pyplot as plt
   >>> plt.ion()
   >>> plt.plot(x,y/z, x2, y2/z2)

   or ipython
   In [1]: %pylab
   In [2]: plot(x,y/z, x2, y2/z2)


"""
import pdb
import os
import sys
import string
import random
import subprocess
import numpy as np
import glob
import time
import copy
import gzip
from scipy import interpolate
import matplotlib.pyplot as plt
from itertools import product

#configuration
#synpledir = /home/callende/synple
synpledir = os.path.dirname(os.path.realpath(__file__))

#relative paths
modeldir = synpledir + "/models"
modelatomdir = synpledir + "/data"
linelistdir = synpledir + "/linelists"
bindir = synpledir + "/bin"
synspec = bindir + "/s54h"
rotin = bindir + "/rotin3"

#internal synspec data files
isdf = ['CIA_H2H2.dat', 'CIA.H2H2.Yi', 'CIA_H2H.dat', 'CIA_H2He.dat', 'CIA_HHe.dat', \
        'irwin_bc.dat', 'irwin.dat', 'tremblay.dat', \
        'tsuji.atoms', 'tsuji.molec', 'tsuji.molec_bc2']

#other stuff
clight = 299792.458
epsilon = 0.6 #clv coeff.
bolk = 1.38054e-16  # erg/ K
zero = " 0 "
one =  " 1 "
two =  " 2 "



def syn(modelfile, wrange, dw=None, strength=1e-4, vmicro=None, abu=None, \
    linelist=['gfallx3_bpo.19','kmol3_0.01_30.20'], atom='ap18', vrot=0.0, fwhm=0.0, \
    steprot=0.0, stepfwhm=0.0,  clean=True, save=False, synfile=None, lte=None, 
    compute=True, tmpdir=None):

  """Computes a synthetic spectrum

  Interface to the fortran codes synspec/rotin that only requires two mandatory inputs: 
  a model atmosphere (modelfile) and the limits of the spectral range (wrange). The code 
  recognizes Kurucz, MARCS and Phoenix LTE model atmospheres. The sampling of the frequency 
  grid is chosen internally, but can also be set by adding a constant wavelength step (dw).
  The abundances and microturbulence velocity can be set through the abu and vmicro 
  parameters, but default values will be taken from the model atmosphere. Rotational and 
  Gaussian broadening can be introduced (vrot and fwhm parameters). The computed spectrum 
  can be written to a file (save == True). 


  Parameters
  ----------
  modelfile : str
      file with a model atmosphere
  wrange: tuple or list of two floats
      initial and ending wavelengths (angstroms)
  dw: float, optional
      wavelength step for the output fluxes
      this will trigger interpolation at the end
      (default is None for automatic frequency selection)
  strength: float, optional
      threshold in the line-to-continuum opacity ratio for 
      selecting lines (default is 1e-4)
  vmicro: float, optional
      microturbulence (km/s) 
      (default is taken from the model atmosphere)
  abu: array of floats (99 elements), optional
      chemical abundances relative to hydrogen (N(X)/N(H))
      (default taken from input model atmosphere)
  linelist: array of str
      filenames of the line lists, the first one corresponds to 
      the atomic lines and all the following ones (optional) to
      molecular lines
      (default ['gfallx3_bpo.19','kmol3_0.01_30.20'] from Allende Prieto+ 2018)
  atom: str
      'ap18' -- generic opacities used in Allende Prieto+ 2018
      'yo19' -- restricted set for NLTE calculations for APOGEE 2019 (Osorio+ 2019)
      'hhm' -- continuum opacity is simplified to H and H-
      (default 'ap18')
  vrot: float
      projected rotational velocity (km/s)
      (default 0.)
  steprot: float
      wavelength step for convolution with rotational kernel (angstroms)
      set to 0. for automatic adjustment (default 0.)
  fwhm: float
      Gaussian broadening: macroturbulence, instrumental, etc. (angstroms)
      (default 0.)
  stepfwhm: float
      wavelength step for Gaussian convolution (angstroms)
      set to 0. for automatic adjustment (default 0.)
  clean: bool
      True by the default, set to False to avoid the removal of the synspec
      temporary files/links (default True)
  save: bool
      set to True to save the computed spectrum to a file (default False)
      the root of the model atmosphere file, with an extension ".syn" will be used
      but see the parameter synfile to change that
  synfile: str
      when save is True, this can be used to set the name of the output file
      (default None)
  lte: bool
      this flag can be set to True to enforce LTE in NLTE models. MARCS, Kurucz, the 
      class of Phoenix models used here are always LTE models. Tlusty models
      can be LTE or NLTE, and this keyword will ignore the populations and compute
      assuming LTE for a input NLTE Tlusty model.
      (default None)
  compute: bool
      set to False to skip the actual synspec run, triggering clean=False
      (default True)
  tmpdir: string
      a temporary directory with this name will be created to store
      the temporary synspec input/output files, and the synple log file (usually named
      syn.log) will be named as tmpdir_syn.log. When tmp is None a random string is used
      for this folder
      (default None)

  Returns
  -------
  wave: numpy array of floats
      wavelengths (angstroms)
  flux: numpy array of floats
      flux (H_lambda in ergs/s/cm2/A)
  cont: numpy array of floats
      continuum flux (same units as flux)

  """

  #basic checks on the line list and model atmosphere
  linelist, modelfile = checksynspec(linelist,modelfile)

  #read model atmosphere
  atmostype, teff, logg, vmicro2, abu2, nd, atmos = read_model(modelfile)

  if vmicro == None: vmicro = vmicro2
  if abu is None: abu = abu2
  #we take a step of 1/3 of the Gaussian (thermal + micro) FWHM at the lowest T and for an atomic mass of 100
  space = np.mean(wrange) / clight * 2.355 / 3. * np.sqrt(0.1289**2 * np.min(atmos['t']) / 100. + vmicro** 2 / 2.) 

  #check input parameters are valid
  imode = checkinput(wrange, vmicro, linelist)

  #find out additional info for Tlusty models
  if atmostype == 'tlusty':
    madaffile, nonstdfile, nonstd, numpar, datadir, inlte, atommode, atominfo = read_tlusty_extras(modelfile)
    if (inlte == -1): nonstd['IBFAC'] = 1
    if (lte == True): inlte = 0
  else:
    nonstd = None
    inlte = 0
    atommode = None
    atominfo = None


  print(modelfile,'is a',atmostype,' model')
  print ('teff,logg,vmicro=',teff,logg,vmicro)
  #print ('abu=',abu)
  #print (len(abu))
  #print ('nd=',nd)
  #print ('linelist=',linelist)
  #print ('wrange=',wrange)

  logfile = 'syn.log'
  if tmpdir is None:
    tmpdir = ''.join(random.choices(string.ascii_lowercase + string.digits, k = 16))
  startdir = os.getcwd()
  logfile = os.path.join(startdir,os.path.split(tmpdir)[-1]) + "_" + logfile
  try:
    os.mkdir(tmpdir)
  except OSError:
    print( "cannot create tmpdir %s " % (tmpdir) )
  try:
    os.chdir(tmpdir)
  except OSError:
    print("cannot enter tmpdir %s " % (tmpdir) )


  cleanup_fort()
  if os.path.islink('data'): os.unlink('data')
  if os.path.isfile('tas'): os.remove('tas')

  assert (not os.path.isdir('data')), 'A subdirectory *data* exists in this folder, and that prevents the creation of a link to the data directory for synple'

  #link data folder for used-provided model atoms
  dd = ''
  if atmostype == 'tlusty':
    # data dir
    hdd, dd = os.path.split(datadir)
    os.symlink(datadir,dd)
    if dd == 'data':
      for entry in isdf:
        assert (os.path.isfile(os.path.join(dd,entry))), 'Cannot find the data file:'+dd+'/'+entry     
        

  #link the data folder (synspec data + default tlusty model atoms)
  if dd != 'data': os.symlink(modelatomdir,'./data')          #data directory  

  write5(teff,logg,abu,atom,inlte=inlte,atommode=atommode,atominfo=atominfo)   #abundance/opacity file  
  write8(teff,logg,nd,atmos,atmostype)                    #model atmosphere
  write55(wrange,space,imode,inlte,2,strength,vmicro,linelist,atmostype) #synspec control file
  writetas('tas',nd,linelist,nonstd=nonstd)               #non-std param. file
  create_links(linelist)                                  #auxiliary data

  if compute == False:

    wave = None
    flux = None  
    cont = None

  else:

    synin = open('fort.5')
    synout = open(logfile,'w')

    start = time.time()
    p = subprocess.Popen([synspec], stdin=synin, stdout = synout, stderr= synout, shell=True)
    p.wait()

    synout.flush()
    synout.close()
    synin.close()

    assert (os.path.isfile('fort.7')), 'Error: I cannot read the file *fort.7* in '+tmpdir+' -- looks like synspec has crashed, please look at '+logfile

    assert (os.path.isfile('fort.17')), 'Error: I cannot read the file *fort.17* in '+tmpdir+' -- looks like synspec has crashed, please look at '+logfile


    wave, flux = np.loadtxt('fort.7', unpack=True)
    if np.isclose(wave[-1],wave[-2]):
      wave = wave[0:-2]
      flux = flux[0:-2]
    wave2, flux2 = np.loadtxt('fort.17', unpack=True)
    if dw == None and fwhm <= 0. and vrot <= 0.: cont = np.interp(wave, wave2, flux2)
    end = time.time()
    print('syn ellapsed time ',end - start, 'seconds')

    if fwhm > 0. or vrot > 0.:
      start = time.time()
      print( vrot, fwhm, space, steprot, stepfwhm)
      wave, flux = call_rotin (wave, flux, vrot, fwhm, space, steprot, stepfwhm, clean=False, \
        reuseinputfiles=True, logfile=logfile)
      if dw == None: cont = np.interp(wave, wave2, flux2)
      end = time.time()
      print('convol ellapsed time ',end - start, 'seconds')

    if (dw != None): 
      nsamples = int((wrange[1] - wrange[0])/dw) + 1
      wave3 = np.arange(nsamples)*dw + wrange[0]
      cont = np.interp(wave3, wave2, flux2)
      flux = interp_spl(wave3, wave, flux)      
      #flux = np.interp(wave3, wave, flux)
      wave = wave3

    if clean == True: 
      cleanup_fort()
      if os.path.islink('data'): os.unlink('data')
      if os.path.isfile('tas'): os.remove('tas')
      if atmostype == 'tlusty':
        if os.path.islink(dd): os.unlink(dd)


    try:
      os.chdir(startdir)
    except OSError:
      print("cannot change directory from tmpdir %s to startdir %s"  % (tmpdir,startdir) ) 
    if clean == True:
      try:
        os.rmdir(tmpdir)
      except OSError:
        print("cannot remove directory tmpdir %s" % (tmpdir) )
     

    if save == True:
      if synfile == None: 
        tmpstr = os.path.split(modelfile)[-1]
        synfile = tmpstr[:tmpstr.rfind('.')]+'.syn'
      np.savetxt(synfile,(wave,flux,cont))


  return(wave, flux, cont)


def mpsyn(modelfile, wrange, dw=None, strength=1e-4, vmicro=None, abu=None, \
    linelist=['gfallx3_bpo.19','kmol3_0.01_30.20'],atom='ap18', vrot=0.0, fwhm=0.0, \
    steprot=0.0, stepfwhm=0.0,  clean=True, save=False, synfile=None, lte=None,
    compute=True, nthreads=1):

  """Computes a synthetic spectrum, splitting the spectral range in nthreads parallel calculations

  Wrapper for syn, using multiprocessing, to speed-up the calculation of a broad spectral range

  Parameters
  ----------
  modelfile : str
      file with a model atmosphere
  wrange: tuple or list of two floats
      initial and ending wavelengths (angstroms)
  dw: float, optional
      wavelength step for the output fluxes
      this will trigger interpolation at the end
      (default is None for automatic selection)
  strength: float, optional
      threshold in the line-to-continuum opacity ratio for 
      selecting lines (default is 1e-4)
  vmicro: float, optional
      microturbulence (km/s) 
      (default is taken from the model atmosphere)
  abu: array of floats (99 elements), optional
      chemical abundances relative to hydrogen (N(X)/N(H))
      (default taken from input model atmosphere)
  linelist: array of str
      filenames of the line lists, the first one corresponds to 
      the atomic lines and all the following ones (optional) to
      molecular lines
      (default ['gfallx3_bpo.19','kmol3_0.01_30.20'] from Allende Prieto+ 2018)
  atom: str
      'ap18' -- generic opacities used in Allende Prieto+ 2018
      'yo19' -- restricted set for NLTE calculations for APOGEE 2019 (Osorio+ 2019)
      'hhm' -- continuum opacity is simplified to H and H-
      (default 'ap18')
  vrot: float
      projected rotational velocity (km/s)
      (default 0.)
  steprot: float
      wavelength step for convolution with rotational kernel (angstroms)
      set to 0. for automatic adjustment (default 0.)
  fwhm: float
      Gaussian broadening: macroturbulence, instrumental, etc. (angstroms)
      (default 0.)
  stepfwhm: float
      wavelength step for Gaussian convolution (angstroms)
      set to 0. for automatic adjustment (default 0.)
  clean: bool
      True by the default, set to False to avoid the removal of the synspec
      temporary files/links (default True)
  save: bool
      set to True to save the computed spectrum to a file (default False)
      the root of the model atmosphere file, with an extension ".syn" will be used
      but see the parameter synfile to change that
  synfile: str
      when save is True, this can be used to set the name of the output file
      (default None)
  lte: bool
      this flag can be set to True to enforce LTE in NLTE models. MARCS, Kurucz, the 
      class of Phoenix models used here are always LTE models. Tlusty models
      can be LTE or NLTE, and this keyword will ignore the populations and compute
      assuming LTE for a input NLTE Tlusty model.
      (default None)
  compute: bool
      set to False to skip the actual synspec run, triggering clean=False
      (default True)
  nthreads: int
      choose the number of cores to use in the calculation
      (default 1, 0 has the meaning that the code should take all the cores available)

  Returns
  -------
  wave: numpy array of floats
      wavelengths (angstroms)
  flux: numpy array of floats
      flux (H_lambda in ergs/s/cm2/A)
  cont: numpy array of floats
      continuum flux (same units as flux)

  """

  from multiprocessing import Pool,cpu_count


  if nthreads == 0: 
    nthreads = cpu_count()

  tmpdir = ''.join(random.choices(string.ascii_lowercase + string.digits, k = 16))

  delta = (wrange[1]-wrange[0])/nthreads
  pars = []
  for i in range(nthreads):

    wrange1 = (wrange[0]+delta*i,wrange[0]+delta*(i+1))

    pararr = [modelfile, wrange1, dw, strength, vmicro, abu, \
      linelist, atom, vrot, fwhm, \
      steprot, stepfwhm,  clean, save, synfile, lte, \
      compute, tmpdir+'-'+str(i) ]
    pars.append(pararr)

  pool = Pool(nthreads)
  results = pool.starmap(syn,pars)
  pool.close()
  pool.join()

  x = results[0][0]
  y = results[0][1]
  z = results[0][2]

  if len(results) > 1:
    for i in range(len(results)-1):
      x = np.concatenate((x, results[i+1][0][1:]) )
      y = np.concatenate((y, results[i+1][1][1:]) )
      z = np.concatenate((z, results[i+1][2][1:]) )

  return(x,y,z)

def raysyn(modelfile, wrange, dw=None, strength=1e-4, vmicro=None, abu=None, \
    linelist=['gfallx3_bpo.19','kmol3_0.01_30.20'], atom='ap18', vrot=0.0, fwhm=0.0, \
    steprot=0.0, stepfwhm=0.0,  clean=True, save=False, synfile=None, lte=None, 
    compute=True, nthreads=1):

  """Computes a synthetic spectrum, splitting the spectral range in nthreads parallel calculations 

  Wrapper for syn, using ray, to speed-up the calculation of a broad spectral range

  Parameters
  ----------
  modelfile : str
      file with a model atmosphere
  wrange: tuple or list of two floats
      initial and ending wavelengths (angstroms)
  dw: float, optional
      wavelength step for the output fluxes
      this will trigger interpolation at the end
      (default is None for automatic selection)
  strength: float, optional
      threshold in the line-to-continuum opacity ratio for 
      selecting lines (default is 1e-4)
  vmicro: float, optional
      microturbulence (km/s) 
      (default is taken from the model atmosphere)
  abu: array of floats (99 elements), optional
      chemical abundances relative to hydrogen (N(X)/N(H))
      (default taken from input model atmosphere)
  linelist: array of str
      filenames of the line lists, the first one corresponds to 
      the atomic lines and all the following ones (optional) to
      molecular lines
      (default ['gfallx3_bpo.19','kmol3_0.01_30.20'] from Allende Prieto+ 2018)
  atom: str
      'ap18' -- generic opacities used in Allende Prieto+ 2018
      'yo19' -- restricted set for NLTE calculations for APOGEE 2019 (Osorio+ 2019)
      'hhm' -- continuum opacity is simplified to H and H-
      (default 'ap18')
  vrot: float
      projected rotational velocity (km/s)
      (default 0.)
  steprot: float
      wavelength step for convolution with rotational kernel (angstroms)
      set to 0. for automatic adjustment (default 0.)
  fwhm: float
      Gaussian broadening: macroturbulence, instrumental, etc. (angstroms)
      (default 0.)
  stepfwhm: float
      wavelength step for Gaussian convolution (angstroms)
      set to 0. for automatic adjustment (default 0.)
  clean: bool
      True by the default, set to False to avoid the removal of the synspec
      temporary files/links (default True)
  save: bool
      set to True to save the computed spectrum to a file (default False)
      the root of the model atmosphere file, with an extension ".syn" will be used
      but see the parameter synfile to change that
  synfile: str
      when save is True, this can be used to set the name of the output file
      (default None)
  lte: bool
      this flag can be set to True to enforce LTE in NLTE models. MARCS, Kurucz, the 
      class of Phoenix models used here are always LTE models. Tlusty models
      can be LTE or NLTE, and this keyword will ignore the populations and compute
      assuming LTE for a input NLTE Tlusty model.
      (default None)
  compute: bool
      set to False to skip the actual synspec run, triggering clean=False
      (default True)
  nthreads: int
      choose the number of cores to use in the calculation
      (default 1, 0 has the meaning that the code should take all the cores available)

  Returns
  -------
  wave: numpy array of floats
      wavelengths (angstroms)
  flux: numpy array of floats
      flux (H_lambda in ergs/s/cm2/A)
  cont: numpy array of floats
      continuum flux (same units as flux)

  """

  import psutil
  import ray

  @ray.remote
  def fun(vari,cons):

    wrange,tmpdir = vari

    modelfile,dw,strength,vmicro,abu,linelist, \
    atom,vrot,fwhm,steprot,stepfwhm,clean,save,synfile,compute = cons

    x, y, z = syn(modelfile, wrange, dw, strength, vmicro, abu, \
              linelist, atom, vrot, fwhm, \
              steprot, stepfwhm,  clean, save, synfile, lte, \
              compute, tmpdir)

    return(x,y,z)


  if nthreads == 0: 
    nthreads = psutil.cpu_count(logical=False)

  print('nthreads=',nthreads)

  tmpdir = ''.join(random.choices(string.ascii_lowercase + string.digits, k = 16))

  ray.init(num_cpus=nthreads)

  rest = [ modelfile,dw,strength,vmicro,abu,linelist, \
    atom,vrot,fwhm,steprot,stepfwhm,clean,save,synfile,compute ]

  constants = ray.put(rest)

  delta = (wrange[1]-wrange[0])/nthreads
  pars = []
  for i in range(nthreads):

    wrange1 = (wrange[0]+delta*i,wrange[0]+delta*(i+1))
    folder = tmpdir+'-'+str(i)

    pararr = [wrange1, folder ]
    pars.append(pararr)

  results = ray.get([fun.remote(pars[i],constants) for i in range(nthreads)])

  x = results[0][0]
  y = results[0][1]
  z = results[0][2]

  if len(results) > 1:
    for i in range(len(results)-1):
      x = np.concatenate((x, results[i+1][0][1:]) )
      y = np.concatenate((y, results[i+1][1][1:]) )
      z = np.concatenate((z, results[i+1][2][1:]) )

  return(x,y,z)



def multisyn(modelfiles, wrange, dw=None, strength=1e-4, abu=None, \
    vmicro=None, vrot=0.0, fwhm=0.0, nfe=0.0, \
    linelist=['gfallx3_bpo.19','kmol3_0.01_30.20'], atom='ap18', \
    steprot=0.0, stepfwhm=0.0,  clean=True, save=None, lte=None, nthreads=1):

  """Computes synthetic spectra for a list of files. The values of vmicro, vrot, 
  fwhm, and nfe can be iterables. Whether or not dw is specified the results will be 
  placed on a common wavelength scale by interpolation. When not specified, dw will be 
  chosen as appropriate for the first model in modelfiles.


  Parameters
  ----------
  modelfiles : list of str
      files with model atmospheres
  wrange: tuple or list of two floats
      initial and ending wavelengths (angstroms)
  dw: float
      wavelength step for the output fluxes.
      Unlike in 'syn', interpolation to a constant step will always be done
      (default is None for automatic selection based on the first model of the list)
  strength: float, optional
      threshold in the line-to-continuum opacity ratio for 
      selecting lines (default is 1e-4)
  abu: array of floats (99 elements), optional
      chemical abundances relative to hydrogen (N(X)/N(H))
      (default taken from input model atmosphere)
  vmicro: float, optional, can be an iterable
      microturbulence (km/s) 
      (default is taken from the model atmosphere)
  vrot: float, can be an iterable
      projected rotational velocity (km/s)
      (default 0.)
  fwhm: float, can be an iterable
      Gaussian broadening: macroturbulence, instrumental, etc. (angstroms)
      (default 0.)
  nfe: float, can be an iterable
      [N/Fe] nitrogen abundance change from the one specified in the array 'abu' (dex)
      (default 0.)
  linelist: array of str
      filenames of the line lists, the first one corresponds to 
      the atomic lines and all the following ones (optional) to
      molecular lines
      (default ['gfallx3_bpo.19','kmol3_0.01_30.20'] from Allende Prieto+ 2018)
  atom: str
      'ap18' -- generic opacities used in Allende Prieto+ 2018
      'yo19' -- restricted set for NLTE calculations for APOGEE 2019 (Osorio+ 2019)
      'hhm' -- continuum opacity is simplified to H and H-
      (default 'ap18')
  steprot: float
      wavelength step for convolution with rotational kernel (angstroms)
      set to 0. for automatic adjustment (default 0.)
  stepfwhm: float
      wavelength step for Gaussian convolution (angstroms)
      set to 0. for automatic adjustment (default 0.)
  clean: bool
      True by the default, set to False to avoid the removal of the synspec
      temporary files/links (default True)
  save: bool
      set to True to save the computed spectra to files (default False)
      the root of the model atmosphere file, with an extension ".syn" will be used
      if multiple values of vmicro, vrot, fwhm or nfe are used, their values are
      prepended to the file names 
      (default None)
  lte: bool
      this flag can be set to True to enforce LTE in NLTE models. MARCS, Kurucz, the 
      class of Phoenix models used here are always LTE models. Tlusty models
      can be LTE or NLTE, and this keyword will ignore the populations and compute
      assuming LTE for a input NLTE Tlusty model.
      (default None)
  nthreads: int
      choose the number of cores to use in the calculation
      (default 1, 0 has the meaning that the code should take all the cores available)



  Returns
  -------
  wave: numpy array of floats (1D)
      wavelengths (angstroms)
  flux: numpy array of floats (2D -- as many rows as models input)
      flux (H_lambda in ergs/s/cm2/A)
  cont: numpy array of floats (2D -- as many rows as models input)
      continuum flux (same units as flux)

  """


  #when vmicro, vrot, fwhm or nitrogen are not iterables, we create ones, otherwise we copy them
  try: 
    nvmicro = len(vmicro)
    vmicros = vmicro
  except TypeError:
    nvmicro = 1
    vmicros = [ vmicro ] 
  try: 
    nvrot = len(vrot)
    vrots = vrots
  except TypeError:
    nvrot = 1
    vrots = [ vrot ]   
  try: 
    nfwhm = len(fwhm)
    fwhms = fwhm
  except TypeError:
    nfwhm = 1
    fwhms = [ fwhm ]   
  try: 
    nnfe = len(nfe)
    nnfes = nfe
  except TypeError:
    nnfe = 1
    nfes = [ nfe ] 

  assert (len(modelfiles) > 0), 'multisyn needs at least one model to work with'
  wave = None
  flux = None
  cont = None

  for entry in modelfiles:
    for vmicro1 in vmicros:
      for nfe1 in nfes:

        abu1 = copy.copy(abu)        

        #if need be, adjust nitrogen abundance according to nfe
        if (abs(nfe1) > 1e-7):
          if (abu1 == None):
            linelist, entry = checksynspec(linelist,entry)
            atmostype, teff, logg, vmicro2, abu1, nd, atmos = read_model(entry)
          abu1[6] = abu1[6] * 10.**nfe1

        x, y, z = mpsyn(entry, wrange, dw=None, strength=strength, \
        vmicro=vmicro1, abu=abu1, linelist=linelist, atom=atom, \
        clean=clean, save=save, lte=lte, nthreads=nthreads)

        space = np.mean(np.diff(x))
            
        for vrot1 in vrots:
          for fwhm1 in fwhms:

            if fwhm1> 0. or vrot1 > 0.:
              start = time.time()
              print( entry, vmicro1, nfe1, vrot1, fwhm1, space)
              x2, y2 = call_rotin (x, y, vrot, fwhm, space, steprot, stepfwhm, \
              clean=False, reuseinputfiles=True)
              z2 = np.interp(x2, x, z)
              end = time.time()
              print('convol ellapsed time ',end - start, 'seconds')
            else:
              x2, y2, z2 = x, y, z


            if entry == modelfiles[0] and vmicro1 == vmicros[0] and vrot1 == vrots[0] and fwhm1 == fwhms[0] and nfe1 == nfes[0]:
              if dw == None: dw = np.median(np.diff(x2))
              nsamples = int((wrange[1] - wrange[0])/dw) + 1
              wave = np.arange(nsamples)*dw + wrange[0]
              #flux = np.interp(wave, x2, y2)
              flux = interp_spl(wave, x2, y2)
              cont = np.interp(wave, x2, z2)
            else:
              #flux = np.vstack ( (flux, np.interp(wave, x, y) ) )
              flux = np.vstack ( (flux, interp_spl(wave, x, y) ) )
              cont = np.vstack ( (cont, np.interp(wave, x, z) ) )


  return(wave, flux, cont)



def polysyn(modelfiles, wrange, dw=None, strength=1e-4, abu=None, \
    vmicro=None, vrot=0.0, fwhm=0.0, nfe=0.0, \
    linelist=['gfallx3_bpo.19','kmol3_0.01_30.20'],atom='ap18', \
    steprot=0.0, stepfwhm=0.0,  clean=True, save=None, lte=None):

  """Sets up a directory tree for computing synthetic spectra for a list of files in 
  parallel. The values of vmicro, vrot, fwhm, and nfe can be iterables. Whether or not 
  dw is specified the results will be placed on a common wavelength scale by interpolation.
  When not specified, dw will be chosen as appropriate for the first model in modelfiles.


  Parameters
  ----------
  modelfiles : list of str
      files with model atmospheres
  wrange: tuple or list of two floats
      initial and ending wavelengths (angstroms)
  dw: float
      Unlike in 'syn', interpolation to a constant step will always be done
      (default is None for automatic selection based on the first model of the list)
  strength: float, optional
      threshold in the line-to-continuum opacity ratio for 
      selecting lines (default is 1e-4)
  abu: array of floats (99 elements), optional
      chemical abundances relative to hydrogen (N(X)/N(H))
      (default taken from input model atmosphere)
  vmicro: float, optional, can be an iterable
      microturbulence (km/s) 
      (default is taken from the model atmosphere)
  vrot: float, can be an iterable
      projected rotational velocity (km/s)
      (default 0.)
  fwhm: float, can be an iterable
      Gaussian broadening: macroturbulence, instrumental, etc. (angstroms)
      (default 0.)
  nfe: float, can be an iterable
      [N/Fe] nitrogen abundance change from the one specified in the array 'abu' (dex)
      (default 0.)
  linelist: array of str
      filenames of the line lists, the first one corresponds to 
      the atomic lines and all the following ones (optional) to
      molecular lines
      (default ['gfallx3_bpo.19','kmol3_0.01_30.20'] from Allende Prieto+ 2018)
  atom: str
      'ap18' -- generic opacities used in Allende Prieto+ 2018
      'yo19' -- restricted set for NLTE calculations for APOGEE 2019 (Osorio+ 2019)
      'hhm' -- continuum opacity is simplified to H and H-
      (default 'ap18')
  steprot: float
      wavelength step for convolution with rotational kernel (angstroms)
      set to 0. for automatic adjustment (default 0.)
  stepfwhm: float
      wavelength step for Gaussian convolution (angstroms)
      set to 0. for automatic adjustment (default 0.)
  clean: bool
      True by the default, set to False to avoid the removal of the synspec
      temporary files/links (default True)
  save: bool
      set to True to save the computed spectra to files (default False)
      the root of the model atmosphere file, with an extension ".syn" will be used
      if multiple values of vmicro, vrot, fwhm or nfe are used, their values are
      prepended to the file names 
      (default None)
  lte: bool
      this flag can be set to True to enforce LTE in NLTE models. MARCS, Kurucz, the 
      class of Phoenix models used here are always LTE models. Tlusty models
      can be LTE or NLTE, and this keyword will ignore the populations and compute
      assuming LTE for a input NLTE Tlusty model.
      (default None)

  Returns
  -------
  wave: numpy array of floats (1D)
      wavelengths (angstroms)
  flux: numpy array of floats (2D -- as many rows as models input)
      flux (H_lambda in ergs/s/cm2/A)
  cont: numpy array of floats (2D -- as many rows as models input)
      continuum flux (same units as flux)

  """

  #synspec does not currently run in parallel
  nthreads = 1


  #when vmicro, vrot, fwhm or nitrogen are not iterables, we create ones, otherwise we copy them
  try: 
    nvmicro = len(vmicro)
    vmicros = vmicro
  except TypeError:
    nvmicro = 1
    vmicros = [ vmicro ] 
  try: 
    nvrot = len(vrot)
    vrots = vrots
  except TypeError:
    nvrot = 1
    vrots = [ vrot ]   
  try: 
    nfwhm = len(fwhm)
    fwhms = fwhm
  except TypeError:
    nfwhm = 1
    fwhms = [ fwhm ]   
  try: 
    nnfe = len(nfe)
    nnfes = nfe
  except TypeError:
    nnfe = 1
    nfes = [ nfe ] 


  idir = 0
  for entry in modelfiles:
    for vmicro1 in vmicros:
      for nfe1 in nfes:

        idir = idir + 1
        dir = ( "hyd%07d" % (idir) )
        try:
          os.mkdir(dir)
        except OSError:
          print( "cannot create dir hyd%07d" % (idir) )
        try:
          os.chdir(dir)
        except OSError:
          print( "cannot change dir to hyd%07d" % (idir) )

        if entry == 'missing':
          pass
        else:
          #setup the slurm script
          sfile = dir+".job"
          now=time.strftime("%c")
          s = open(sfile ,"w")
          s.write("#!/bin/bash \n")
          s.write("#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-# \n")
          s.write("#This script was written by synple on "+now+" \n") 
          s.write("#SBATCH  -J "+dir+" \n")
          s.write("#SBATCH  -o "+dir+"_%j.out"+" \n")
          s.write("#SBATCH  -e "+dir+"_%j.err"+" \n")
          s.write("#SBATCH  -n "+str(nthreads)+" \n")
          s.write("#SBATCH  -t 04:00:00"+" \n") #hh:mm:ss
          s.write("#SBATCH  -D "+os.path.abspath(os.curdir)+" \n")
          s.write("#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-# \n\n\n")


          abu1 = copy.copy(abu)

          #if need be, adjust nitrogen abundance according to nfe
          if (abs(nfe1) > 1e-7):
            if (abu1 == None):
              linelist, entry = checksynspec(linelist,entry)
              atmostype, teff, logg, vmicro2, abu1, nd, atmos = read_model(entry)
            abu1[6] = abu1[6] * 10.**nfe1

          x, y, z = syn(entry, wrange, dw=None, strength=strength, vmicro=vmicro1, \
          abu=abu1, linelist=linelist, atom=atom, lte=lte, compute=False)

          s.write(synspec+" < "+"fort.5"+"\n")

          si = open("fort.55",'r')
          for i in range(6): line = si.readline()
          entries = line.split()
          space = float(entries[5])
          si.close()
            
          iconv = 0
          for vrot1 in vrots:
            for fwhm1 in fwhms:

              print('iconv=',iconv)

              iconv = iconv + 1
              inconv = ("%07dfort.5" % (iconv) )
              outconv = ("'%07dfort.7'" % (iconv) )
              if fwhm1> 0. or vrot1 > 0.:
                f = open(inconv,'w')
                f.write( ' %s %s %s \n' % ("'fort.7'", "'fort.17'", outconv) )
                f.write( ' %f %f %f \n' % (vrot1, space, steprot) )
                f.write( ' %f %f \n' % (fwhm1, stepfwhm) )
                print('stepfwhm=',stepfwhm)
                f.write( ' %f %f %i \n' % (wrange[0], wrange[1], 0) )
                f.close()
                s.write(rotin+" < "+inconv+"\n")
              else:
                s.write("cp "+" fort.7 "+outconv[1:-1]+"\n")

          s.close()
          os.chmod(sfile ,0o755)

        try:
          os.chdir('..')
        except OSError:
          print( "cannot exit dir hyd%07d" % (idir) )


  return(None,None,None)



def polyopt(wrange=(9.e2,1.e5),dw=0.1,strength=1e-3, linelist=['gfallx3_bpo.19','kmol3_0.01_30.20'], \
    tlt = (20,3.08,0.068), tlrho = (20,-14.0,0.59), \
    tfeh=(1,0.0,0.0), tafe=(1,0.0,0.0), tcfe=(1,0.0,0.0), tnfe=(1,0.0,0.0), \
    tofe=(1,0.0,0.0), trfe=(1,0.0,0.0), tsfe=(1,0.0,0.0), tvmicro=(1,1.0,0.0), \
    zexclude=None, atom='ap18'):

  """Sets up a directory tree for computing opacity tables for TLUSTY. The table collection forms 
  a regular grid defined by triads in various parameters. Each triad has three values (n, llimit, step)
  that define an array x = np.range(n)*step + llimit. Triads in teff (tteff) and logg
  (tlogg) are mandatory. Triads in [Fe/H] (tfeh), [alpha/Fe] (tafe), [C/Fe] (tcfe), 
  [N/Fe] (tnfe), [O/Fe] (tofe), [r/Fe] (rfe), and [s/Fe] (sfe) are optional since 
  arrays with just one 0.0 are included by default.

  Parameters
  ----------
  wrange: tuple or list of two floats
      initial and ending wavelengths (angstroms)
  dw: float
      Unlike in 'syn', interpolation to a constant step will always be done
      (default is None for automatic selection based on the first model of the list)
  strength: float, optional
      threshold in the line-to-continuum opacity ratio for 
      selecting lines (default is 1e-4)
  linelist: array of str
      filenames of the line lists, the first one corresponds to 
      the atomic lines and all the following ones (optional) to
      molecular lines
      (default ['gfallx3_bpo.19','kmol3_0.01_30.20'] from Allende Prieto+ 2018)
  atom: str
      'ap18' -- generic opacities used in Allende Prieto+ 2018
      'yo19' -- restricted set for NLTE calculations for APOGEE 2019 (Osorio+ 2019)
      'hhm' -- continuum opacity is simplified to H and H-
      (default 'ap18')
  tlt: tuple
    log10(T) triad (n, llimit, step) for opacity grid
    (default values  chosen for grid lt = np.arange(20)*0.068 + 3.08,
     to cover the range in the DR16 APOGEE MARCS grids)
  tlrho: tuple
    log10(rho) triad (n, llimit, step) for opacity grid
    (default values  chosen for grid lrho = np.arange(20)*0.59 -14.0,
     to cover the range in the DR16 APOGEE MARCS grids)
  tteff: tuple
    Teff triad (n, llimit, step)
  tlogg: tuple
    logg triad (n, llimit, step)
  tfeh: tuple
    [Fe/H] triad
  tafe: tuple
    [alpha/Fe] triad  
  tcfe: tuple
    [C/Fe] triad
  tnfe: tuple
    [N/Fe] triad
  tofe: tuple
    [O/Fe] triad
  rfeh: tuple
    [r/Fe] triad (r-elements abundance ratio)
  sfeh: tuple
    [s.Fe] triad (s-elements abundance ratio)
  zexclude: list
    atomic numbers of the elements whose opacity is NOT to be
    included in the table
    (default None)

  """

  #pynspec does not currently run in parallel
  nthreads = 1

  #expanding the triads t* into iterables
  try: 
    nfeh = len(tfeh)
    assert (nfeh == 3), 'Error: feh triad must have three elements (n, llimit, step)'
    fehs = np.arange(tfeh[0])*tfeh[2] + tfeh[1]
  except TypeError:
    print('Error: feh triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nafe = len(tafe)
    assert (nafe == 3), 'Error: afe triad must have three elements (n, llimit, step)'
    afes = np.arange(tafe[0])*tafe[2] + tafe[1]
  except TypeError:
    print('Error: afe triad must have three elements (n, llimit, step)')
    return ()

  try: 
    ncfe = len(tcfe)
    assert (ncfe == 3), 'Error: cfe triad must have three elements (n, llimit, step)'
    cfes = np.arange(tcfe[0])*tcfe[2] + tcfe[1]
  except TypeError:
    print('Error: cfe triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nnfe = len(tnfe)
    assert (nnfe == 3), 'Error: nfe triad must have three elements (n, llimit, step)'
    nfes = np.arange(tnfe[0])*tnfe[2] + tnfe[1]
  except TypeError:
    print('Error: nfe triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nofe = len(tofe)
    assert (nofe == 3), 'Error: ofe triad must have three elements (n, llimit, step)'
    ofes = np.arange(tofe[0])*tofe[2] + tofe[1]
  except TypeError:
    print('Error: ofe triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nrfe = len(trfe)
    assert (nrfe == 3), 'Error: rfe triad must have three elements (n, llimit, step)'
    rfes = np.arange(trfe[0])*trfe[2] + trfe[1]
  except TypeError:
    print('Error: rfe triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nsfe = len(tsfe)
    assert (nsfe == 3), 'Error: sfe triad must have three elements (n, llimit, step)'
    sfes = np.arange(tsfe[0])*tsfe[2] + tsfe[1]
  except TypeError:
    print('Error: sfe triad must have three elements (n, llimit, step)')
    return ()
  
  try: 
    nvmicro = len(tvmicro)
    assert (nvmicro == 3), 'Error: vmicro triad must have three elements (n, llimit, step)'
    vmicros = np.arange(tvmicro[0])*tvmicro[2] + tvmicro[1]
  except TypeError:
    print('Error: vmicro triad must have three elements (n, llimit, step)')
    return ()
  

  #ranges for the opacity table
  try: 
    nlt = len(tlt)
    assert (nlt == 3), 'Error: lt triad must have three elements (n, llimit, step)'
    lt = np.arange(tlt[0])*tlt[2] + tlt[1]  #log10(T)
  except TypeError:
    print('Error: tlt triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nlrho = len(tlrho)
    assert (nlrho == 3), 'Error: lrho triad must have three elements (n, llimit, step)'
    lrho = np.arange(tlrho[0])*tlrho[2] + tlrho[1] #log10(density)
  except TypeError:
    print('Error: tlrho triad must have three elements (n, llimit, step)')
    return ()

  
  symbol, mass, sol = elements()
  z_metals = np.arange(97,dtype=int) + 3
  #Ar usually included among alphas in MARCS and not in Kurucz/Meszaros
  z_alphas = np.array([8,10,12,14,16,18,20,22],dtype=int) 
  # rs increases: notes and data below from comments in the MARCS code (provided by B.Edvardsson) 
  # Fractional r-process abundance for Ga-Bi (r+s simply assumed == 100%) | Date 2000-01-18
  # (Note: Ga-Sr (31-38) was just copied from Kaeppeler et al. 1989, below)
  # s-process from Stellar models: Arlandini C., Kaeppeler F., Wisshak K.,
  # Gallino R., Busso M., Straniero O., 1999, Astrophys J. 525, 886-900
  #   Fractions corrected to the revised meteoritic abundances
  #   of Grevesse N., Sauval A.J. 1998, Space Science Review 85, 161-174  
  # -0.99 is assigned to unstable elements
  z_rs = np.arange(62,dtype=int) + 31
  rfrac= np.array([.43, .47, .81, .85, .39, .47, 
                   .41, .11, .08, .17, .15, .50,-.99, .68, .86, 
                   .54, .80, .48, .65, .35, .75, .83, .80, .80, 
                   .85, .19, .38, .23, .51, .44,-.99, .71, .93, 
                   .85, .93, .85, .92, .83, .87, .67, .80, .44, 
                   .59, .44, .91, .91, .99, .95, .94, .41, .24, 
                   .54, .95,-.99,-.99,-.99,-.99,-.99,-.99, 1.0, 
                   -.99, 1.0], dtype=float)                     



  idir = 0
  for feh in fehs:
    for afe in afes:
      for cfe in cfes:
        for nfe in nfes:
          for ofe in ofes:
            for rfe in rfes:
              for sfe in sfes: 
                for vmicro in vmicros:
                
                  print(feh,afe,cfe,nfe,ofe,rfe,sfe)

                  idir = idir + 1
                  dir = ( "hyd%07d" % (idir) )
                  try:
                    os.mkdir(dir)
                  except OSError:
                    print( "cannot create dir hyd%07d" % (idir) )
                  try:
                    os.chdir(dir)
                  except OSError:
                    print( "cannot change dir to hyd%07d" % (idir) )

                  #check input parameters are valid
                  imode = checkinput(wrange, vmicro, linelist)

                  #setup the slurm script
                  sfile = dir+".job"
                  now=time.strftime("%c")
                  s = open(sfile ,"w")
                  s.write("#!/bin/bash \n")
                  s.write("#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-# \n")
                  s.write("#This script was written by synple on "+now+" \n") 
                  s.write("#SBATCH  -J "+dir+" \n")
                  s.write("#SBATCH  -o "+dir+"_%j.out"+" \n")
                  s.write("#SBATCH  -e "+dir+"_%j.err"+" \n")
                  s.write("#SBATCH  -n "+str(nthreads)+" \n")
                  s.write("#SBATCH  --ntasks-per-node "+str(4)+" \n")
                  s.write("#SBATCH  -t 48:00:00"+" \n") #hh:mm:ss
                  s.write("#SBATCH  -D "+os.path.abspath(os.curdir)+" \n")
                  s.write("#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-#-# \n\n\n")

                
                  abu = copy.copy(sol)

                  if (abs(feh) > 1e-7): 
                    for i in range(len(z_metals)): 
                      abu[z_metals[i] - 1] = abu[z_metals[i] - 1] * 10.**feh
                  if (abs(afe) > 1e-7): 
                    for i in range(len(z_alphas)):
                      abu[z_alphas[i] - 1] = abu[z_alphas[i] - 1] * 10.**afe
                  if (abs(cfe) > 1e-7): abu[5] = abu[5] * 10.**cfe
                  if (abs(nfe) > 1e-7): abu[6] = abu[6] * 10.**nfe
                  if (abs(ofe) > 1e-7): abu[7] = abu[7] * 10.**ofe
                  if (abs(rfe) > 1e-7): 
                      for i in range(len(z_rs)): 
                        if rfrac[i] > 0.0: abu[z_rs[i] - 1] = abu[z_rs[i] - 1] * rfrac[i] * 10.**rfe
                  if (abs(sfe) > 1e-7): 
                      for i in range(len(z_rs)): 
                        if rfrac[i] > 0.0: abu[z_rs[i] - 1] = abu[z_rs[i] - 1] * (1.0 - rfrac[i]) * 10.**sfe


                  write55(wrange,dw=dw,imode=-3,inlte=0,hydprf=0, \
                  strength=strength, vmicro=vmicro, linelist=linelist)

                  write5(9999.,9.9,abu,atom)
                  
                  writetas('tas',1,linelist)

                  write2(lt,lrho,wrange,filename='opt.dat', \
                  strength=strength,inttab=1)

                  if zexclude != None: 
                    write3(zexclude)
                    
                  create_links(linelist)
                  
                  s.write('time ' + synspec + " < "+"fort.5"+"\n")
                  s.close()
                  os.chmod(sfile ,0o755)
                  
                  try:
                    os.chdir('..')
                  except OSError:
                    print( "cannot exit dir hyd%07d" % (idir) )		  

  return()




def collect_marcs(modeldir=modeldir, tteff=None, tlogg=None, tfeh=(1,0.0,0.0), tafe=(1,0.0,0.0), \
  tcfe=(1,0.0,0.0), tnfe=(1,0.0,0.0), tofe=(1,0.0,0.0), trfe=(1,0.0,0.0), tsfe=(1,0.0,0.0), \
    ignore_missing_models=False, ext='mod'):

  """Collects all the MARCS models in modeldir that are part of a regular grid defined
  by triads in various parameters. Each triad has three values (n, llimit, step)
  that define an array x = np.range(n)*step + llimit. Triads in teff (tteff) and logg
  (tlogg) are mandatory. Triads in [Fe/H] (tfeh), [alpha/Fe] (tafe), [C/Fe] (tcfe), 
  [N/Fe] (tnfe), [O/Fe] (tofe), [r/Fe] (rfe), and [s/Fe] (sfe) are optional since 
  arrays with just one 0.0 are included by default.

  Parameters
  ----------
  modeldir: str
    directory where model atmosphere files are
  tteff: tuple
    Teff triad (n, llimit, step)
  tlogg: tuple
    logg triad (n, llimit, step)
  tfeh: tuple
    [Fe/H] triad
  tafe: tuple
    [alpha/Fe] triad  
  tcfe: tuple
    [C/Fe] triad
  tnfe: tuple
    [N/Fe] triad
  tofe: tuple
    [O/Fe] triad
  rfeh: tuple
    [r/Fe] triad (r-elements abundance ratio)
  sfeh: tuple
    [s.Fe] triad (s-elements abundance ratio)
  ignore_missing_models: bool
    set to True to avoid stopping when a model is missing,
    in which case a None is entered in the returning list
 
  Returns
  -------
  files: list of str
    file names with MARCS models that are in modeldir and match
    the parameters in the requested grid

  """

  #expanding the triads t* into iterables
  try: 
    nteff = len(tteff)
    assert (nteff == 3), 'Error: Teff triad must have three elements (n, llimit, step)'
    teffs = np.arange(tteff[0])*tteff[2] + tteff[1]
  except TypeError:
    print('Error: Teff triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nlogg = len(tlogg)
    assert (nlogg == 3), 'Error: logg triad must have three elements (n, llimit, step)'
    loggs = np.arange(tlogg[0])*tlogg[2] + tlogg[1]
  except TypeError:
    print('Error: logg triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nfeh = len(tfeh)
    assert (nfeh == 3), 'Error: feh triad must have three elements (n, llimit, step)'
    fehs = np.arange(tfeh[0])*tfeh[2] + tfeh[1]
  except TypeError:
    print('Error: feh triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nafe = len(tafe)
    assert (nafe == 3), 'Error: afe triad must have three elements (n, llimit, step)'
    afes = np.arange(tafe[0])*tafe[2] + tafe[1]
  except TypeError:
    print('Error: afe triad must have three elements (n, llimit, step)')
    return ()

  try: 
    ncfe = len(tcfe)
    assert (ncfe == 3), 'Error: cfe triad must have three elements (n, llimit, step)'
    cfes = np.arange(tcfe[0])*tcfe[2] + tcfe[1]
  except TypeError:
    print('Error: cfe triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nnfe = len(tnfe)
    assert (nnfe == 3), 'Error: nfe triad must have three elements (n, llimit, step)'
    nfes = np.arange(tnfe[0])*tnfe[2] + tnfe[1]
  except TypeError:
    print('Error: nfe triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nofe = len(tofe)
    assert (nofe == 3), 'Error: ofe triad must have three elements (n, llimit, step)'
    ofes = np.arange(tofe[0])*tofe[2] + tofe[1]
  except TypeError:
    print('Error: ofe triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nrfe = len(trfe)
    assert (nrfe == 3), 'Error: rfe triad must have three elements (n, llimit, step)'
    rfes = np.arange(trfe[0])*trfe[2] + trfe[1]
  except TypeError:
    print('Error: rfe triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nsfe = len(tsfe)
    assert (nsfe == 3), 'Error: sfe triad must have three elements (n, llimit, step)'
    sfes = np.arange(tsfe[0])*tsfe[2] + tsfe[1]
  except TypeError:
    print('Error: sfe triad must have three elements (n, llimit, step)')
    return ()

  files = []

  fi = open('files.txt','w')

  for teff in teffs:
    for logg in loggs:
      for feh in fehs:
        for afe in afes:
          for cfe in cfes:
            for nfe in nfes:
              for ofe in ofes:
                for rfe in rfes:
                  for sfe in sfes: 
                
                    print(teff,logg,feh,afe,cfe,nfe,ofe,rfe,sfe)
                    code = 'm*_t*_x3'

                    if logg >= 3.5: 
                      a1 = 'p' 
                    else: 
                      a1 = 's'

                    sformat = "%s%4i_g%+.1f_%s_z%+.2f_a%+.2f_c%+.2f_n%+.2f_o%+.2f_r%+.2f_s%+.2f."+ext+"*"
                    filename = (sformat % (a1,teff,logg,code,feh,afe,cfe,nfe,ofe,rfe,sfe) )

                    file = glob.glob(os.path.join(modeldir,'**',filename),recursive=True)
                    

                    if ignore_missing_models == False:
                      assert len(file) > 0, 'Cannot find model '+filename+' in modeldir '+modeldir                   
                      assert len(file) == 1, 'More than one model matches '+filename+' in modeldir '+modeldir
                    else:
                      if (len(file) == 0): files.append('missing')
                      
                    if (len(file) == 1): files.append(file[0])

                    fi.write( "%s  %4i %+.1f %+.2f %+.2f %+.2f %+.2f %+.2f %+.2f %+.2f\n" % (files[-1],teff,logg,feh,afe,cfe,nfe,ofe,rfe,sfe) )



  fi.close()

  return(files)

def collect_k2odfnew(modeldir=modeldir, tteff=None, tlogg=None, tfeh=(1,0.0,0.0), tafe=(1,0.0,0.0), \
    ignore_missing_models=False):

  """Collects all the ODFNEW Castelli/Kurucz models in modeldir that are part of a regular grid defined
  by triads in various parameters. Each triad has three values (n, llimit, step)
  that define an array x = np.range(n)*step + llimit. Triads in teff (tteff) and logg
  (tlogg) are mandatory. Triads in [Fe/H] (tfeh), and [alpha/Fe] (tafe) are optional since 
  arrays with just one 0.0 are included by default. 

  NOTE: There are ODFNEW models with only afe=[alpha/Fe]=0.0 or 0.4. The latter are used whenever
  afe takes values > 0.0, while the afe=0.0 models are used otherwise.

  Parameters
  ----------
  modeldir: str
    directory where model atmosphere files are
  tteff: tuple
    Teff triad (n, llimit, step)
  tlogg: tuple
    logg triad (n, llimit, step)
  tfeh: tuple
    [Fe/H] triad
  tafe: tuple
    [alpha/Fe] triad  
  ignore_missing_models: bool
    set to True to avoid stopping when a model is missing,
    in which case a None is entered in the returning list
  ext: str
    extension of the model files, usually 'mod' for MARCS but
    could be '.7' or '.22' for Tlusty NLTE models based on MARCS
    (default 'mod')
 
  Returns
  -------
  files: list of str
    file names with Kurucz ODFNEWS models that are in modeldir and match
    the parameters in the requested grid

  """

  #expanding the triads t* into iterables
  try: 
    nteff = len(tteff)
    assert (nteff == 3), 'Error: Teff triad must have three elements (n, llimit, step)'
    teffs = np.arange(tteff[0])*tteff[2] + tteff[1]
  except TypeError:
    print('Error: Teff triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nlogg = len(tlogg)
    assert (nlogg == 3), 'Error: logg triad must have three elements (n, llimit, step)'
    loggs = np.arange(tlogg[0])*tlogg[2] + tlogg[1]
  except TypeError:
    print('Error: logg triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nfeh = len(tfeh)
    assert (nfeh == 3), 'Error: feh triad must have three elements (n, llimit, step)'
    fehs = np.arange(tfeh[0])*tfeh[2] + tfeh[1]
  except TypeError:
    print('Error: feh triad must have three elements (n, llimit, step)')
    return ()

  try: 
    nafe = len(tafe)
    assert (nafe == 3), 'Error: afe triad must have three elements (n, llimit, step)'
    afes = np.arange(tafe[0])*tafe[2] + tafe[1]
  except TypeError:
    print('Error: afe triad must have three elements (n, llimit, step)')
    return ()


  files = []

  fi = open('files.txt','w')

  for teff in teffs:
    for logg in loggs:
      for feh in fehs:
        for afe in afes:
                
                    print(teff,logg,feh,afe)
                    code = 'k2odfnew.dat'

                    if afe > 0.0: 
                      a1 = 'a' 
                    else: 
                      a1 = ''

                    if feh < 0.0:
                      a2 = 'am'
                    else:
                      a2 = 'ap'

                    filename = ("t%05ig%.1f%s%02i%s" % (teff,logg,a2,int(abs(feh)*10),a1+code) )

                    file = glob.glob(os.path.join(modeldir,'**',filename), recursive = True)


                    if ignore_missing_models == False:
                      assert len(file) > 0, 'Cannot find model '+filename+' in modeldir '+modeldir                   
                      assert len(file) == 1, 'More than one model matches '+filename+' in modeldir '+modeldir
                    else:
                      if (len(file) == 0): files.append('missing')
                      
                    if (len(file) == 1): files.append(file[0])

                    fi.write( "%s  %4i %+.1f %+.2f %+.2f \n" % (files[-1],teff,logg,feh,afe) )

  fi.close()

  return(files)



def getallt(modelfiles):

  """Collects all the values for temperature, density and electron number density
  in a list of files with model atmospheres

  Parameters
  ----------
  modelfiles : list of str
      files with model atmospheres

  Returns
  -------
  t: list
    list of all temperatures in all the layers of the input model atmospheres    
  rho: list
    list of all values of gas pressure in all the layers of the input model atmospheres
    
  ne: list
    list of all values of electron number density in all the layers of the input model atmospheres

  """

  t = []
  rho = []
  ne = []

  for entry in modelfiles:
    print('reading ',entry)
    teff, logg, vmicro, abu, nd, atmos = read_marcs_model2(entry)
    #atmostype,teff,logg,vmicro,abu,nd,atmos = read_model(entry)
    for value in atmos['t']: t.append(value)
    for value in atmos['rho']: rho.append(value)
    for value in atmos['ne']:  ne.append(value)

  return(t,rho,ne)



def call_rotin(wave=None, flux=None, vrot=0.0, fwhm=0.0, space=1e-2, steprot=0.0, 
stepfwhm=0.0, clean=True, reuseinputfiles=False, logfile='syn.log'):


  """Convolves a synthetic spectrum with a rotation and/or Gaussian kernel

  Interface to the fortran code rotin.

  Parameters
  ----------
  wave: numpy array of floats
      wavelengths (angstroms)
  flux: numpy array of floats
      flux 
  vrot: float
      projected rotational velocity (km/s)
      (default 0.)
  space: float, optional
      characteristic wavelength scale for variations in the spectrum (angstroms)
      (default is 1e-2)
  steprot: float
      wavelength step for convolution with rotational kernel (angstroms)
      set to 0. for automatic adjustment (default 0.)
  fwhm: float
      Gaussian broadening: macroturbulence, instrumental, etc. (angstroms)
      (default 0.)
  stepfwhm: float
      wavelength step for Gaussian convolution (angstroms)
      set to 0. for automatic adjustment (default 0.)
  clean: bool
      True by the default, set to False to avoid the removal of the rotin
      temporary files (default Tr<ue)
  reuseinputfiles: bool
      set to take the input data from the output synspec file (fort.7) rather than 
      from the input arrays (wave, flux)
  logfile: str
      name of the log file
      (default syn.log)

  Returns
  -------
  wave2: numpy array of floats
      wavelengths (angstroms)
  flux2: numpy array of floats
      flux 


  """
  if reuseinputfiles == False:
    f = open('fort.7','w')
    f2 = open('fort.17','w')
    maxflux = np.max(flux)
    for i in range(len(wave)):
      f.write( ' %f %f \n' % (wave[i], flux[i]) )
      f2.write( ' %f %f \n' % (wave[i], maxflux) )
    f.close()
    f2.close()

  f = open('fort.5','w')
  f.write( ' %s %s %s \n' % ("'fort.7'", "'fort.17'", "'fort.11'") )
  f.write( ' %f %f %f \n' % (vrot, space, steprot) )
  f.write( ' %f %f \n' % (fwhm, stepfwhm) )
  print('stepfwhm=',stepfwhm)
  f.write( ' %f %f %i \n' % (np.min(wave), np.max(wave), 0) )
  f.close()

  synin = open('fort.5')
  synout = open(logfile,'a')
  p = subprocess.Popen([rotin], stdin=synin, stdout = synout, stderr = synout)
  p.wait()
  synout.flush()
  synout.close()
  synin.close()
  
  assert (os.path.isfile('fort.11')), 'Error: I cannot read the file *fort.11* in '+os.getcwd()+' -- looks like rotin has crashed, please look at syn.log'

  wave2, flux2 = np.loadtxt('fort.11', unpack=True)
  print(len(wave),len(wave2))
  
  if clean == True: cleanup_fort()

  return(wave2, flux2)

def read_model(modelfile):
  
  """Reads a model atmosphere into a structure
  
  Parameters
  ----------  
  modelfile : str
      file with a model atmosphere
      
  Returns
  -------
  atmostype :  str
      type of model atmosphere (kurucz/marcs/phoenix/tlusty)
  teff : float
      effective temperature (K)
  logg : float
      log10 of the surface gravity (cm s-2)
  vmicro : float
      microturbulence velocity (km/s)
  abu : list
      abundances, number densities of nuclei relative to hydrogen N(X)/N(H)
      for elements Z=1,99 (H to Es)
  nd: int
      number of depths (layers) of the model
  atmos: numpy structured array
      array with the run with depth of column mass, temperature, gas pressure 
      and electron density
  """

  #check
  if not os.path.isfile(modelfile):
    mf = os.path.join(modeldir,modelfile)
    if os.path.isfile(mf): modelfile = mf


  atmostype = identify_atmostype(modelfile)

  if atmostype == 'kurucz':
    teff, logg, vmicro, abu, nd, atmos = read_kurucz_model(modelfile) 
  if atmostype == 'marcs':
    teff, logg, vmicro, abu, nd, atmos = read_marcs_model2(modelfile)
  if atmostype == 'phoenix':
    teff, logg, vmicro, abu, nd, atmos = read_phoenix_model(modelfile)
  if atmostype == 'tlusty':
    teff, logg, vmicro, abu, nd, atmos = read_tlusty_model(modelfile)

  return (atmostype,teff,logg,vmicro,abu,nd,atmos)

def identify_atmostype(modelfile):

  """Idenfies the type of model atmosphere in an input file

  Valid options are kurucz, marcs, tlusty (.7) or phoenix

  Parameters
  ----------
  modelfile: str
      file with a model atmosphere

  Returns
  -------
  atmostype: str
      can take the value 'kurucz', 'marcs', 'tlusty' or 'phoenix' 

  """

  if ('PHOENIX' in modelfile and 'fits' in modelfile): atmostype = 'phoenix'
  else: 
    if modelfile[-3:] == '.gz':
      f = gzip.open(modelfile,'rt')
    else:
      f = open(modelfile,'r')
    line = f.readline()
    #print('modelfile / line=',modelfile,line)
    type(line)
    if ('TEFF' in line): atmostype = 'kurucz'
    else: 
      line = f.readline()
      if ('Teff' in line):
        atmostype = 'marcs'
      else:
        atmostype = 'tlusty'
    f.close()
   
  return(atmostype)

def checksynspec(linelist,modelfile):

  """checking that executables and data are where it should be. Prepend
     default directories to linelist and model atmosphere files when necessary

  Parameters
  ----------
  linelist: array of str
      file names of the line lists to be used. The first string should correspond
      to the atomic line list and is mandatory. The remainder are optional and
      correspond to molecular line lists. All files should be in synspec format.
      (see documentation at http://nova.astro.umd.edu/Synspec43/synspec.html)

  """

  dirs = [synpledir,modelatomdir,linelistdir,bindir]
  for entry in dirs: assert (os.path.isdir(entry)), 'dir '+entry+' missing'

  i = 0 
  for entry in linelist: 
    if os.path.isfile(entry):
      if not os.path.isabs(entry): 
        ll = os.path.join (os.getcwd(), entry)
        if os.path.isfile(ll): linelist[i] = ll
    else:
      ll = os.path.join(linelistdir,entry)
      if os.path.isfile(ll): linelist[i] = ll
    i = i + 1

  files = [synspec,rotin]
  for entry in linelist: files.append(entry)
  for entry in files: assert (os.path.isfile(entry)), 'file '+entry+' missing'

  if not os.path.isfile(modelfile):
    mf = os.path.join(modeldir,modelfile)
    if os.path.isfile(mf): modelfile = mf

  #print(modeldir)
  #print(modelfile)
  assert (os.path.isfile(modelfile)),'model atmosphere file '+modelfile+' missing'


  return(linelist,modelfile)


def checkinput(wrange, vmicro, linelist):

  """checking input parameters from user


  Parameters
  ----------
  wrange: tuple or list of two floats
      initial and ending wavelengths (angstroms)
  vmicro: float, optional
      microturbulence (km/s) 
      (default is taken from the model atmosphere)
  linelist: array of str
      filenames of the line lists, the first one corresponds to 
      the atomic lines and all the following ones (optional) to
      molecular lines
      (default ['gfallx3_bpo.19','kmol3_0.01_30.20'] from Allende Prieto+ 2018)

  Returns
  ------
  imode: int
      appropriate value for the variable imode, which specifies whether
      one will use many atomic lines (imode=0), just a few (imode=1),
      or none (H lines are an exception; imode=2)

  """


  #determine imode
  # imode = 0  is default, atoms and molecules, at least 2 line lists 
  # synple sets IFMOL = 1 in 'tas' when an input molecular line list is used
  # but does not set it when only an atomic line list is given
  # imode = 2 for pure continuum
  # imode = 1 for few-lines mode
  # imode = -3 for regular opacity tables (TLUSTY)

  if len(linelist) == 0: 
    imode = 2  # no atomic or molecular line list -> pure continuum and no molecules
  else:

    nlines, minlambda, maxlambda = getlinelistrange(linelist[0])

    #check
    if nlines > 10:
      assert (wrange[0] > minlambda-1 and wrange[1] < maxlambda+1),'wrange exceeds the allow range ('+str(minlambda)+' to '+str(maxlambda)+')'
      imode = 0
    else:
      imode = 1

    assert (vmicro >= 0.0),'vmicro = '+str(vmicro)+' but cannot < 0.'
  
  return(imode)

def getlinelistrange(atomiclinelist):
#finds out min and max wavelengths for a line list

  f = open(atomiclinelist,'r')
  line = f.readline()
  entries = line.split()
  minlambda = float(entries[0])*10.
  fsize = os.path.getsize(atomiclinelist)
  f.seek(fsize-103)
  line = f.readline()
  f.close()
  entries = line.split()
  maxlambda = float(entries[0])*10.
  nlines = int(0.01 * fsize)

  return(nlines, minlambda,maxlambda)



def writetas(filename,nd,linelist,nonstd=None):
#write non-std input parameters
# input: filename -- str -- name of the non-std. param. file to print
#        nd -- int -- number of layers in the model
#        linelist -- list -- names of the linelist files (atomic first, then one 
#				or more molecular ones
#        nonstd -- dict -- additional entries to add to the tas file 
#
  
  f = open(filename,'w')

  if nonstd is not None:
    for entry in nonstd.keys():
      f.write(entry + "=" + str(nonstd[entry])+"\n")

  f.write("ND= "+str(nd)+" \n")
  if len(linelist) > 1:  f.write("IFMOL= "+one+" \n")
  f.write("TMOLIM= 8000. \n")


  f.close()

  return()

def write3(zexclude):
  
  f = open('fort.3','w')
  for z in zexclude:
    f.write( " %d %10.4e \n" % (z, 0.0) )
  f.close()
  
  return()


def write2(lt,lrho,wrange, filename='opt.data', dlw=2e-5, binary=False,strength=1e-4,inttab=1):
#write fort.2 file for creating opacity tables for TLUSTY

  f = open('fort.2','w')
  f.write( " %d %10.4e %10.4e \n" % (len(lt),10.**lt[0],10.**lt[-1]) )
  f.write( " %d \n" % (1) )
  f.write( " %d %10.4e %10.4e \n" % (len(lrho),10.**lrho[0],10.**lrho[-1]) )
  
  nsamples = int( (np.log10(wrange[1]) - np.log10(wrange[0]) )/dlw) + 1 
  f.write( " %d %d %10.4e %10.4e \n" % (nsamples,inttab,wrange[0],wrange[1]) )  
  if binary == True: 
    ibingr = 1
  else:
    ibingr = 0
  filename = "'"+filename+"'"
  f.write( " %s %d \n" % (filename,ibingr) )
  f.close()

  return()


def write55(wrange,dw=1e-2,imode=0,inlte=0,hydprf=2,strength=1e-4,vmicro=0.0, \
  linelist=['gfallx3_bpo.19','kmol3_0.01_30.20'], atmostype='kurucz'):


  #imode,idst,iprin
  #inmod,zero,ichang,ichemc
  #lyman,zero,zero,zero,zero
  #one,nlte,icontl,inlist,ifhe2
  #ihydpr,ihe1pr,ihe2pr
  #wstart,wend,cutoff,zero,strength,wdist 

  if (atmostype == 'tlusty' or atmostype == 'marcs'): inmod = 1 
  else: inmod = 0

  inlist = 11
  for file in linelist:
    binaryfile = file[:-2]+'11'
    if not os.path.isfile(binaryfile): inlist = 10
    if os.path.isfile(binaryfile): assert (inlist == 11), 'The line list files must be all either in ascii or binary!'    

  f = open('fort.55','w')
  f.write(" "+str(imode)+" "+2*zero+"\n")
  f.write(" "+str(inmod)+3*zero+"\n")
  f.write(5*zero+"\n")
  f.write(one+str(abs(inlte))+zero+str(inlist)+zero+"\n")
  f.write(str(hydprf)+2*zero+"\n")
  if imode == -3:
    f.write( ' %f %f %f %i %e %f \n ' % (wrange[0],  -wrange[1], 100., 2000, strength, dw) )
  else:
    f.write( ' %f %f %f %i %e %f \n ' % (wrange[0],   wrange[1], 200., 2000, strength, dw) )
  ll = len(linelist)
  if ll < 2: f.write(2*zero)
  else: f.write(str(ll-1) + ' ' + ' '.join(map(str,np.arange(ll-1)+20)))
  f.write("\n")
  f.write( ' %f  \n' % (vmicro) )
  f.close()

def write5(teff,logg,abu, atom='ap18', ofile='fort.5', inlte=0, atommode=None, atominfo=None):

  symbol, mass, sol = elements()

  f = open(ofile,'w')
  f.write(' '+str(teff)+" "+str(logg).format('%7.4f')+"       ! TEFF, GRAV \n")
  if inlte == 0:
    f.write(" T  F               ! LTE, GRAY \n")
  else:
    f.write(" F  F               ! LTE, GRAY \n")

  f.write(" 'tas'              ! name of non-standard flags \n")
  f.write(" 50                 ! frequencies \n")

  natom = len(abu)
  f.write(" "+str(natom)+"        ! NATOMS \n")  

  assert (atom == 'hhm' or atom == 'ap18' or atom == 'yo19' or atom == 'test'), 'atom must be one of: hhm/ap18/yo19/test!'
  ex = np.ones(natom)
  if atom == 'hhm' : 
    zex = [1]  #atomic numbers of elements included explicitly (contributing cont. opacity)
  elif atom == 'yo19':
    zex = [1,11,12,19,20]
  elif atom == 'test': 
    zex = [1,26]
  elif atom == 'ap18': 
    zex = [1,2,6,7,8,11,12,13,14,20,26]

  for i in zex: ex[i-1] = 2

  #tlusty models provide atommode and atominfo that override the defaults for atom and ex
  if atommode is not None: ex = np.array(atommode)
  if atominfo is not None: atom = 'own'

  for i in range(natom):
    f.write(' %2d %e %i %s\n' %  (ex[i], abu[i], 0, '  ! ' +symbol[i]) )

  for i in range(3): f.write("* \n")
  
  if atom == 'hhm':  # highly simplified continuum opacities -- just H and H-
    f.write("* ../data_atom for ions  \n")
    f.write("   1   -1     1      0     0     1    ' H 1' 'data/hm.dat' \n" )
    f.write("   0    0     3      0 \n")
    f.write("   1    0     9      0     0     0    ' H 1' 'data/h1s.dat'  \n")
    f.write("   1    1     1      1     0     0    ' H 2' ' '  \n")
    f.write("   0    0     0     -1     0     0    '    ' ' '  \n")
    f.write("* \n")
    f.write("* end \n")
  elif atom == "yo19": # set for NLTE calculations for APOGEE (see Osorio+ 2019 A&A paper)
    f.write("* ../data_atom for ions  \n")
    f.write("  1    -1     1      0     0     1    ' H 0' 'data/hm.dat'  \n")
    f.write("  0     0     3      0   \n")
    f.write("  1     0     16     0     0     0    ' H 1' 'data/h1_16lev2.dat'  \n")
    f.write("  1     1     1      1     0     0    ' H 2' ' '  \n")
    f.write("  11    0     42     0     0     0    'Na 1' 'data/NaIkas.tl'  \n")
    f.write("  11    1     1      1     0     0    'Na 2' '' \n")
    f.write("  12    0     96     0     0     0    'Mg 1' 'data/Mg1kas_F_ccc.sy'  \n")
    f.write("  12    1     29     0     0     0    'Mg 2' 'data/Mg2kas_F_ccc.sy'  \n")
    f.write("  12    2     1      1     0     0    'Mg 3' ' '  \n")
    f.write("  19    0     31     0     0     0    'K  1' 'data/KIkas.tl'  \n")
    f.write("  19    1     1      1     0     0    'K  2' ''  \n")
    f.write("  20    0     66     0     0     0    'Ca 1' 'data/Ca1kas_F_zat.sy'  \n")
    f.write("  20    1     24     0     0     0    'Ca 2' 'data/Ca2kas_F_zat.sy'  \n")
    f.write("  20    2     1      1     0     0    'Ca 3' ' '  \n")
    f.write("   0    0     0     -1     0     0    '    ' ' '  \n")
    f.write("* \n")
    f.write("* end \n")
  elif atom == 'test': # generic set used in Allende Prieto+ (2018) A&A paper
    f.write("* ../data for ions  \n")
    f.write("   1   -1     1      0     0     1    ' H 1' 'data/hm.dat'  \n")
    f.write("   0    0     3      0 \n")
    f.write("   1    0     9      0     0     0    ' H 1' 'data/h1s.dat'  \n")
    f.write("   1    1     1      1     0     0    ' H 2' ' '  \n")
    f.write("  26    0     49     0     0     0    'Fe 1' 'data/tlusty_fe1_topmod.dat'  \n")
    f.write("  26    1     41     0     0     0    'Fe 2' 'data/tlusty_fe2_topmod.dat'  \n")
    f.write("  26    2     1      1     0     0    'Fe 3' ' '  \n")
    f.write("  0     0     0     -1     0     0    '    ' ' '  \n")
    f.write("* \n")
    f.write("* end \n")
  elif atom == 'ap18': # generic set used in Allende Prieto+ (2018) A&A paper
    f.write("* ../data for ions  \n")
    f.write("   1   -1     1      0     0     1    ' H 1' 'data/hm.dat'  \n")
    f.write("   0    0     3      0 \n")
    f.write("   1    0     9      0     0     0    ' H 1' 'data/h1s.dat'  \n")
    f.write("   1    1     1      1     0     0    ' H 2' ' '  \n")
    f.write("   2    0     14     0     0     0    'He 1' 'data/he1.dat'  \n")
    f.write("   2    1     14     0     0     0    'He 2' 'data/he2.dat '  \n")
    f.write("   2    2     1      1     0     0    'He 3' ' '  \n")
    f.write("   6    0     104    0     0     0    ' C 1' 'data/c1.t'  \n")
    f.write("   6    1     40     0     0     0    ' C 2' 'data/c2.t'  \n")
    f.write("   6    2     1      1     0     0    ' C 3' ' '  \n")
    f.write("   7    0     89     0     0     0    ' N 1' 'data/n1.t'  \n")
    f.write("   7    1     51     0     0     0    ' N 2' 'data/n2.t'  \n")
    f.write("   7    2     1      1     0     0    ' N 3' ' '  \n")
    f.write("   8    0     54     0      0    0    ' O 1' 'data/o1.t'  \n")
    f.write("   8    1     74     0      0    0    ' O 2' 'data/o2.t'  \n")
    f.write("   8    2     1      1      0    0    ' O 3' ' '  \n")
    f.write("  11    0     32     0     0     0    'Na 1' 'data/na1.t'  \n")
    f.write("  11    1     8      0     0     0    'Na 2' 'data/na2.t'  \n")
    f.write("  11    2     1      1     0     0    'Na 3' ' '  \n")
    f.write("  12    0     71     0     0     0    'Mg 1' 'data/mg1.t'  \n")
    f.write("  12    1     31     0     0     0    'Mg 2' 'data/mg2.t'  \n")
    f.write("  12    2     1      1     0     0    'Mg 3' ' '  \n")
    f.write("  13    0     33     0     0     0    'Al 1' 'data/al1.t'  \n")
    f.write("  13    1     81     0     0     0    'Al 2' 'data/al2.t'  \n")
    f.write("  13    2     1      1     0     0    'Al 3' ' '  \n")
    f.write("  14    0     57     0     0     0    'Si 1' 'data/si1.t'  \n")
    f.write("  14    1     46     0     0     0    'Si 2' 'data/si2.t'  \n")
    f.write("  14    2     1      1     0     0    'Si 3' ' '  \n")
    f.write("  20    0     79     0     0     0    'Ca 1' 'data/ca1.t'  \n")
    f.write("  20    1     32     0     0     0    'Ca 2' 'data/ca2.t'  \n")
    f.write("  20    2     1      1     0     0    'Ca 3' ' '  \n")
    f.write("  26    0     49     0     0     0    'Fe 1' 'data/tlusty_fe1_topmod.dat'  \n")
    f.write("  26    1     41     0     0     0    'Fe 2' 'data/tlusty_fe2_topmod.dat'  \n")
    f.write("  26    2     1      1     0     0    'Fe 3' ' '  \n")
    f.write("  0     0     0     -1     0     0    '    ' ' '  \n")
    f.write("* \n")
    f.write("* end \n")
  else:
    for line in atominfo: f.write(line)
  f.close()


def write8(teff, logg, nd, atmos, atmostype, ofile='fort.8'):

  """Writes the model atmosphere for synspec

     MARCS models can be passed in 'Tlusty' (default, after read with 
           read_marcs_models2) or 'Kurucz' format
     Phoenix and Kurucz models are passed to synspec formatted as 'Kurucz'

  """

  f = open(ofile,'w')

  if atmostype == 'tlusty':

    if ('n' in atmos.dtype.names):  # 4th column is number density n
      if ('pop' in atmos.dtype.names):   # explicit (usually NLTE) populations
        numpop = len(atmos['pop'][0]) 
        sformat = '  %f %e %e %e'
        i = 5
        for entry in atmos['pop'][0]: 
           sformat = sformat + ' %e'
           if i % 6 == 0: sformat = sformat + '  \n'
           i = i + 1
        sformat = sformat + ' \n' 
        f.write(" "+str(nd)+" "+str(-(4+numpop))+"\n")
        for i in range(nd):
          f.write(' %e ' % atmos['dm'][i])
          if (i+1) % 5 == 0: f.write('\n')
        if (i+1) % 5 != 0: f.write('\n')
        for i in range(nd):
          sdata = [atmos['t'][i], atmos['ne'][i], atmos['rho'][i], atmos['n'][i]]
          for j in range(numpop):
            sdata.append(atmos['pop'][i][j])
          f.write( sformat % tuple(sdata) )                 
      elif ('dep' in atmos.dtype.names): # NLTE departure coefficients
        numpop = len(atmos['dep'][0]) 
        sformat = '  %f %e %e %e'
        i = 5
        for entry in atmos['dep'][0]: 
           sformat = sformat + ' %e'
           if i % 6 == 0: sformat = sformat + '  \n'
           i = i + 1
        sformat = sformat + ' \n' 
        f.write(" "+str(nd)+" "+str(-(4+numpop))+"\n")
        for i in range(nd):
          f.write(' %e ' % atmos['dm'][i])
          if (i+1) % 5 == 0: f.write('\n')
        if (i+1) % 5 != 0: f.write('\n')
        for i in range(nd):
          sdata = [atmos['t'][i], atmos['ne'][i], atmos['rho'][i], atmos['n'][i]]
          for j in range(numpop):
            sdata.append(atmos['dep'][i][j])
          f.write( sformat % tuple(sdata) )         
      else:                              # LTE
        f.write(" "+str(nd)+" "+str(-4)+"\n")
        for i in range(nd):
          f.write(' %e ' % atmos['dm'][i])
          if (i+1) % 5 == 0: f.write('\n')
        if (i+1) % 5 != 0: f.write('\n')
        for i in range(nd):
          f.write( '%f %e %e %e \n' % (atmos['t'][i], atmos['ne'][i], atmos['rho'][i], atmos['n'][i] ) )  
    else:
      pass

  else:

    if atmostype == 'marcs':
      f.write(" "+str(nd)+" "+str(-4)+"\n")
      for i in range(nd):
        f.write(' %e ' % atmos['dm'][i])
      f.write("\n")
      for i in range(nd):
        f.write( '%f %e %e %e \n' % (atmos['t'][i], atmos['ne'][i], atmos['rho'][i], atmos['rho'][i]/atmos['mmw'][i]/1.67333e-24 + atmos['ne'][i] ) )

    else:
      f.write( 'TEFF %7.0f  GRAVITY %7.5f  LTE \n' % (teff, logg) )
      for i in range(21): f.write('\n')
      f.write( 'READ DECK6%3i RHOX,T,P,XNE \n' % nd )
      for i in range(nd): 
        f.write( '%e %f %e %e \n' % (atmos['dm'][i], atmos['t'][i], atmos['p'][i], atmos['ne'][i]) )
      
  f.close()

  return()
  

def create_links(linelist):
#create soft links for line lists

  for i in range(len(linelist)):
    file = linelist[i]
    binaryfile = linelist[i][:-2]+'11'
    if os.path.isfile(binaryfile): file = binaryfile
    if i == 0: os.symlink(file,'fort.19')
    else: os.symlink(file,'fort.'+str(20-1+i))

  return()

def cleanup_fort():
#cleanup all fort* files


  files = os.listdir('.')
  for entry in files: 
    if os.path.islink(entry) and entry.startswith('fort'): os.unlink(entry)
    if os.path.isfile(entry) and entry.startswith('fort'): os.remove(entry)

  return()


def read_kurucz_model(modelfile):
  
  """Reads a Kurucz model atmospheres
  
  Parameters
  ----------
  modelfile: str
      file name  
  
  Returns
  -------

  teff : float
      effective temperature (K)
  logg : float
      log10 of the surface gravity (cm s-2)
  vmicro : float
      microturbulence velocity (km/s)
  abu : list
      abundances, number densities of nuclei relative to hydrogen N(X)/N(H)
      for elements Z=1,99 (H to Es)
  nd: int
      number of depths (layers) of the model
  atmos: numpy structured array
      array with the run with depth of column mass, temperature, gas pressure 
      and electron density  
  
  """

  f = open(modelfile,'r')
  line = f.readline()
  entries = line.split()
  assert (entries[0] == 'TEFF' and entries[2] == 'GRAVITY'), 'Cannot find Teff and logg in the file header'
  teff = float(entries[1])
  logg = float(entries[3])

  while entries[0] != 'ABUNDANCE':  
    line = f.readline()
    entries = line.split()

  abu = []

  if entries[1] == 'SCALE': 
    scale = float(entries[2])
    

  while entries[0] == 'ABUNDANCE':
    i = 0
    for word in entries: 
      if (word == 'CHANGE'): w = i
      i = i + 1 
    for i in range(int((len(entries)-w-1)/2)):
      z = int(entries[w+1+2*i])
      if (z == 1): nhntot = float(entries[w+2+2*i])
      if (z < 3): abu.append(float(entries[w+2+2*i]) / nhntot) 
      else: abu.append(scale*10.**(float(entries[w+2+2*i])) / nhntot)

    line = f.readline()
    entries = line.split() 

  assert (entries[0] == 'READ'), 'I cannot find the header of the atmospheric table in the input Kurucz model'

  nd = int(entries[2]) - 1
  line = f.readline()
  entries = line.split()
  line = f.readline()
  entries = line.split()
  vmicro = float(entries[6])/1e5

  dm = [ float(entries[0]) ]
  t = [ float(entries[1]) ]
  p = [ float(entries[2]) ]
  ne = [ float(entries[3]) ] 

  for i in range(nd-1):
    line = f.readline()
    entries = line.split()
    dm.append( float(entries[0]))
    t.append(  float(entries[1]))
    p.append(  float(entries[2]))
    ne.append( float(entries[3]))

  atmos = np.zeros(nd, dtype={'names':('dm', 't', 'p','ne'),
                          'formats':('f', 'f', 'f','f')}) 
  atmos['dm'] = dm
  atmos['t'] = t
  atmos['p'] = p
  atmos['ne'] = ne

  return (teff,logg,vmicro,abu,nd,atmos)


def read_marcs_model(modelfile):
  
  """Reads a MARCS model atmospheres
  
  Parameters
  ----------
  modelfile: str
      file name. It can be a gzipped (.gz) file
  
  Returns
  -------

  teff : float
      effective temperature (K)
  logg : float
      log10 of the surface gravity (cm s-2)
  vmicro : float
      microturbulence velocity (km/s)
  abu : list
      abundances, number densities of nuclei relative to hydrogen N(X)/N(H)
      for elements Z=1,99 (H to Es)
  nd: int
      number of depths (layers) of the model
  atmos: numpy structured array
      array with the run with depth of column mass, temperature, gas pressure 
      and electron density  
  
  """  

  if modelfile[-3:] == '.gz':
    f = gzip.open(modelfile,'rt')
  else:
    f = open(modelfile,'r')
  line = f.readline()
  line = f.readline()
  entries = line.split()
  assert (entries[1] == 'Teff'), 'Cannot find Teff in the file header'
  teff = float(entries[0])
  line = f.readline()
  line = f.readline()
  entries = line.split()
  assert (entries[1] == 'Surface' and entries[2] == 'gravity'), 'Cannot find logg in the file header'
  logg = np.log10(float(entries[0]))
  line = f.readline()
  entries = line.split()
  assert (entries[1] == 'Microturbulence'), 'Cannot find vmicro in the file header'
  vmicro = float(entries[0])

  while entries[0] != 'Logarithmic':  
    line = f.readline()
    entries = line.split()

  abu = []
  line = f.readline()
  entries = line.split()

  i = 0
  while entries[1] != 'Number':
    for word in entries: 
      abu.append( 10.**(float(word)-12.0) )
      i = i + 1 
    line = f.readline()
    entries = line.split() 

  if i < 99: 
    for j in range(99-i):
      abu.append(1e-111)
      i = i + 1

  nd = int(entries[0])
  line = f.readline()
  entries = line.split()

  assert (entries[0] == 'Model'), 'I cannot find the header of the atmospheric table in the input MARCS model'

  line = f.readline()
  line = f.readline()
  entries = line.split()

  t = [ float(entries[4]) ]
  p = [ float(entries[6]) ]
  ne = [ float(entries[5]) / bolk / float(entries[4]) ] 

  for i in range(nd-1):
    line = f.readline()
    entries = line.split()

    t.append(  float(entries[4]))
    p.append(  float(entries[6]))
    ne.append( float(entries[5]) / bolk / float(entries[4]))

  line = f.readline()
  line = f.readline()
  entries = line.split()

  dm = [ float(entries[-1]) ]

  for i in range(nd-1):
    line = f.readline()
    entries = line.split()

    dm.append(  float(entries[-1]))

  atmos = np.zeros(nd, dtype={'names':('dm', 't', 'p','ne'),
                          'formats':('f', 'f', 'f','f')}) 
  atmos['dm'] = dm
  atmos['t'] = t
  atmos['p'] = p
  atmos['ne'] = ne

  return (teff,logg,vmicro,abu,nd,atmos)

def read_marcs_model2(modelfile):
  
  """Reads a MARCS model atmospheres. 
  While read_marcs_model returns T, Pg and Ne in the structure 'atmos'
  read_marcs_model2 returns T, rho, mmw, and Ne.
  
  Parameters
  ----------
  modelfile: str
      file name. It can be a gzipped (.gz) file
  
  Returns
  -------

  teff : float
      effective temperature (K)
  logg : float
      log10 of the surface gravity (cm s-2)
  vmicro : float
      microturbulence velocity (km/s)
  abu : list
      abundances, number densities of nuclei relative to hydrogen N(X)/N(H)
      for elements Z=1,99 (H to Es)
  nd: int
      number of depths (layers) of the model
  atmos: numpy structured array
      array with the run with depth of column mass, temperature, density, 
      mean molecular weight and electron number density  
  
  """  

  if modelfile[-3:] == '.gz':
    f = gzip.open(modelfile,'rt')
  else:
    f = open(modelfile,'r')
  line = f.readline()
  line = f.readline()
  entries = line.split()
  assert (entries[1] == 'Teff'), 'Cannot find Teff in the file header'
  teff = float(entries[0])
  line = f.readline()
  line = f.readline()
  entries = line.split()
  assert (entries[1] == 'Surface' and entries[2] == 'gravity'), 'Cannot find logg in the file header'
  logg = np.log10(float(entries[0]))
  line = f.readline()
  entries = line.split()
  assert (entries[1] == 'Microturbulence'), 'Cannot find vmicro in the file header'
  vmicro = float(entries[0])

  while entries[0] != 'Logarithmic':  
    line = f.readline()
    entries = line.split()

  abu = []
  line = f.readline()
  entries = line.split()

  i = 0
  while entries[1] != 'Number':
    for word in entries: 
      abu.append( 10.**(float(word)-12.0) )
      i = i + 1 
    line = f.readline()
    entries = line.split() 

  if i < 99: 
    for j in range(99-i):
      abu.append(1e-111)
      i = i + 1

  nd = int(entries[0])
  line = f.readline()
  entries = line.split()

  assert (entries[0] == 'Model'), 'I cannot find the header of the atmospheric table in the input MARCS model'

  line = f.readline()
  line = f.readline()
  entries = line.split()

  t = [ float(entries[4]) ]
  p = [ float(entries[6]) ]
  ne = [ float(entries[5]) / bolk / float(entries[4]) ] 

  for i in range(nd-1):
    line = f.readline()
    entries = line.split()

    t.append(  float(entries[4]))
    p.append(  float(entries[6]))
    ne.append( float(entries[5]) / bolk / float(entries[4]))

  line = f.readline()
  line = f.readline()
  entries = line.split()

  rho = [ float(entries[3]) ]
  dm = [ float(entries[-1]) ]
  mmw = [ float(entries[4]) ]

  for i in range(nd-1):
    line = f.readline()
    entries = line.split()
    rho.append( float(entries[3]))
    dm.append(  float(entries[-1]))
    mmw.append(  float(entries[4]))

  atmos = np.zeros(nd, dtype={'names':('dm', 't', 'rho','mmw','ne'),
                          'formats':('f', 'f', 'f','f','f')}) 
  atmos['dm'] = dm
  atmos['t'] = t
  atmos['rho'] = rho
  atmos['mmw'] = mmw
  atmos['ne'] = ne

  return (teff,logg,vmicro,abu,nd,atmos)

def read_tlusty_model(modelfile,startdir=None):
  
  """Reads a Tlusty model atmosphere. 

  Parameters
  ----------
  modelfile: str
      file name (.7, .8, or .22). It will look for the complementary .5 file to read
      the abundances and the micro (when specified in the non-std. parameter file)

  startdir: str
      directory where the calculations are initiated. The code will look at that
      location to find the tlusty model atom directory and the non-std. parameter
      file when a relative path is provided
      (default is None, indicating it is the current working directory)
  
  Returns
  -------

  teff : float
      effective temperature (K)
  logg : float
      log10 of the surface gravity (cm s-2)
  vmicro : float
      microturbulence velocity (km/s), by default 0.0 unless set with the parameter
      VTB in the non-std. parameter file specified in the .5 file
  abu : list
      abundances, number densities of nuclei relative to hydrogen N(X)/N(H)
      for elements Z=1,99 (H to Es)
  nd: int
      number of depths (layers) of the model
  atmos: numpy structured array
      array with the run with depth of column mass, temperature, density
      (other variables that may be included, e.g. populations for NLTE models, 
      are ignored). 

  """  

  assert ((modelfile[-2:] == ".8") | (modelfile[-2:] == ".7") | (modelfile[-3:] == ".22")), 'Tlusty models should end in .7, .8, or .22'
  if modelfile[-2] == ".":
    madaffile = modelfile[:-1]+"5"
  else:
    madaffile = modelfile[:-2]+"5"    
  assert (os.path.isfile(madaffile)),'Tlusty model atmosphere file '+modelfile+' should come with an associated .5 file'

  if startdir is None: startdir = os.getcwd()

  #we start reading the .5
  f = open(madaffile,'r')
  line = f.readline()
  entries = line.split()
  teff = float(entries[0])
  logg = float(entries[1])
  line = f.readline()
  line = f.readline()
  entries = line.split()
  nonstdfile = entries[0][1:-1]

  nonstdfile0 = nonstdfile
  if nonstdfile != '':
    if not os.path.isabs(nonstdfile): 
      mf = os.path.join(startdir,nonstdfile)
      if os.path.isfile(mf): 
        nonstdfile = mf
      else:
        mf = os.path.join(modeldir,nonstdfile)
        nonstdfile = mf

    assert (os.path.exists(nonstdfile)), 'The non-std parameter file indicated in the tlusty model, '+nonstdfile0+', is not present' 

  nonstd={}
  if nonstdfile != '':
    assert (os.path.isfile(nonstdfile)),'Tlusty model atmosphere file '+modelfile+' invokes non-std parameter file, '+nonstdfile+' which is not present'


    ns = open(nonstdfile,'r')
    nonstdarr = ns.readlines()
    ns.close()
    for entry in nonstdarr:
      entries = entry.replace('\n','').split(',')
      for piece in entries:
        sides = piece.split('=')
        nonstd[sides[0].replace(' ','')]= sides[1].replace(' ','')

    print('Tlusty nonstd params=',nonstd)

  #the micro might be encoded as VTB in the nonstdfile!!
  #this is a temporary patch, but need to parse that file
  vmicro = 0.0
  if 'VTB' in nonstd: vmicro = float(nonstd['VTB'])

  line = f.readline()
  line = f.readline()
  entries = line.split()
  natoms = int(entries[0])
  
  abu = []
  for i in range(natoms):
    line = f.readline()
    entries = line.split()
    abu.append( float(entries[1]) )

  if i < 98: 
    for j in range(98-i):
      abu.append(1e-111)
      i = i + 1

  f.close()

  #now the .8
  f = open(modelfile,'r')
  line = f.readline()
  entries = line.split()
  nd = int(entries[0])
  numpar = int(entries[1])
  if (numpar < 0): 
    numpop = abs(numpar) - 4 
  else:
    numpop = numpar - 3

  assert (len(entries) == 2), 'There are more than two numbers in the first line of the model atmosphere'

  dm = read_multiline_fltarray(f,nd)
  atm = read_multiline_fltarray(f,nd*abs(numpar))
  f.close()

  atm = np.reshape(atm, (nd,abs(numpar)) )

  if (numpar < 0):  # 4th column is number density n
    if (numpop > 0): # explicit (usually NLTE) populations
      if modelfile[-2] == ".":  # NLTE populations or departure coefficients
        tp = np.dtype([('dm', 'f'), ('t','f'), ('ne','f'), ('rho','f'), ('n','f'), ('pop', 'f', (numpop))])
      else: 
        tp = np.dtype([('dm', 'f'), ('t','f'), ('ne','f'), ('rho','f'), ('n','f'), ('dep', 'f', (numpop))])
    else:
      tp = np.dtype([('dm', 'f'), ('t','f'), ('ne','f'), ('rho','f'), ('n','f')])  
  else:
    if (numpop > 0):
      if modelfile[-2] == ".": # NLTE populations or departure coefficients
        tp = np.dtype([('dm', 'f'), ('t','f'), ('ne','f'), ('rho','f'), ('pop', 'f', (numpop))])
      else:
        tp = np.dtype([('dm', 'f'), ('t','f'), ('ne','f'), ('rho','f'), ('dep', 'f', (numpop))])
    else:
      tp = np.dtype([('dm', 'f'), ('t','f'), ('ne','f'), ('rho','f') ])

  atmos = np.zeros(nd, dtype=tp)

  atmos['dm'] = dm
  atmos['t'] = atm [:,0]
  atmos['ne'] = atm [:,1]
  atmos['rho'] = atm [:,2]
  if (numpar < 0): atmos['n'] = atm [:,3]
  if (numpop > 0): 
    if modelfile[-2] == ".":
      atmos['pop'] = atm [:,4:]
    else:
      atmos['dep'] = atm [:,4:]

  return (teff,logg,vmicro,abu,nd,atmos)


def read_tlusty_extras(modelfile,startdir=None):
  
  """Identifies and reads the non-std parameter file and its content, finds out the 
     number of parameters in the model, whether the file contains populations or departure
     coefficients, and the name of the data directory for Tlusty 
     model atmospheres. 

  Parameters
  ----------
  modelfile: str
      file name (.8, .7 or .22). It will look for the complementary .5 file to read
      the abundances and other information

  startdir: str
      directory where the calculations are initiated. The code will look at that
      location to find the tlusty model atom directory and the non-std. parameter
      file when a relative path is provided
      (default is None, indicating it is the current working directory)
  
  
  Returns
  -------

  madaffile: str
       model atom data and abundance file (.5 Tlusty file)

  nonstdfile: str
       non-std parameter file 

  nonstd: dict
       content of the non-std parameter file

  numpar: int
       number of parameters (can be negative when the model includes number density)

  datadir: str
       name of the model atom directory

  inlte: int
       0 when the populations are to be computed internally by synspec (LTE)
       1 the Tlusty model contains populations
      -1 the Tlusty model contains departure coefficients

  atommode: list
       mode for each of the atoms included. The code indicates
       0= not considered
       1= implicit (no cont. opacity)
       2= explicit  (see synspec man.)
       4= semi-explicit (see synspec man.)
       5= quasi-explicit  (see synspec. man)

  atominfo: list
       all the lines in the file that provide info on the model atoms used
  
  """  

  assert ((modelfile[-2:] == ".8") | (modelfile[-2:] == ".7") | (modelfile[-3:] == ".22")), 'Tlusty models should end in .7, .8, or .22'
  if modelfile[-2] == ".":
    madaffile = modelfile[:-1]+"5"
  else:
    madaffile = modelfile[:-2]+"5"    
  assert (os.path.isfile(madaffile)),'Tlusty model atmosphere file '+modelfile+' should come with an associated .5 file'

  if startdir is None: startdir = os.getcwd()

  #we start reading the .5
  f = open(madaffile,'r')
  line = f.readline()
  line = f.readline()
  line = f.readline()
  entries = line.split()
  nonstdfile = entries[0][1:-1]

  nonstdfile0 = nonstdfile  
  if nonstdfile != '':
    if not os.path.isabs(nonstdfile): 
      mf = os.path.join(startdir,nonstdfile)
      if os.path.isfile(mf): 
        nonstdfile = mf
      else:
        mf = os.path.join(modeldir,nonstdfile)
        nonstdfile = mf

    assert (os.path.exists(nonstdfile)), 'The non-std parameter file indicated in the tlusty model, '+nonstdfile0+', is not present' 


  nonstd={}
  if nonstdfile != '':
    assert (os.path.isfile(nonstdfile)),'Tlusty model atmosphere file '+modelfile+' invokes non-std parameter file, '+nonstdfile+' which is not present'


    ns = open(nonstdfile,'r')
    nonstdarr = ns.readlines()
    ns.close()
    for entry in nonstdarr:
      entries = entry.replace('\n','').split(',')
      for piece in entries:
        sides = piece.split('=')
        nonstd[sides[0].replace(' ','')]= sides[1].replace(' ','')


  line = f.readline()
  line = f.readline()
  entries = line.split()
  natoms = int(entries[0])
  
  atommode = []
  for i in range(natoms):
    line = f.readline()
    entries = line.split()
    atommode.append(int(entries[0]))

  atominfo = []
  #keep reading until you find 'dat' to identify data directory 
  line = f.readline()
  while True: 
    atominfo.append(line)
    if '.dat' in line: break
    line = f.readline()

  entries = line.split()
  cadena = entries[-1][1:-1]
  datadir, file = os.path.split(cadena)


  datadir0 = datadir
  if datadir != '':
    if not os.path.isabs(datadir): 
      mf = os.path.join(startdir,datadir)
      if os.path.exists(mf): 
        datadir = mf
      else:
        mf = os.path.join(synpledir,datadir)
        datadir = mf

  #continue reading the rest of the file into atominfo
  line = f.readline()
  while True:
    if line == '': break
    atominfo.append(line)
    line = f.readline()

    assert (os.path.exists(datadir)), 'The datadir indicated in the tlusty model, '+datadir0+', is not present' 


  f.close()

  #now the .8
  f = open(modelfile,'r')
  line = f.readline()
  entries = line.split()
  nd = int(entries[0])
  numpar = int(entries[1])
  if abs(numpar) > 4: 
    inlte = 1 
  else: 
    inlte = 0

  if (modelfile[-3:] == ".22"): inlte = -1

  f.close()

  return (madaffile, nonstdfile, nonstd, numpar, datadir, inlte, atommode, atominfo)


def read_phoenix_model(modelfile):

  """Reads a FITS Phoenix model atmospheres
  
  Parameters
  ----------
  modelfile: str
      file name  
  
  Returns
  -------

  teff : float
      effective temperature (K)
  logg : float
      log10 of the surface gravity (cm s-2)
  vmicro : float
      microturbulence velocity (km/s)
  abu : list
      abundances, number densities of nuclei relative to hydrogen N(X)/N(H)
      for elements Z=1,99 (H to Es)
  nd: int
      number of depths (layers) of the model
  atmos: numpy structured array
      array with the run with depth of column mass, temperature, gas pressure 
      and electron density  
  
  """  

  from astropy.io import fits

  h = fits.open(modelfile)[0].header
  f = fits.open(modelfile)[1].data

  nd = len(f['temp'])

  teff = float(h['PHXTEFF'])
  logg = float(h['PHXLOGG'])
  vmicro = float(h['PHXXI_L'])

  m_h = float(h['PHXM_H'])
  alpha = float(h['PHXALPHA'])
  
  symbol, mass,sol = elements(husser=True) 
  abu = sol 
  z_metals = np.arange(97,dtype=int) + 3
  z_alphas = np.array([8,10,12,14,16,20,22],dtype=int)
  for i in range(len(z_metals)): abu[z_metals[i] - 1] = abu[z_metals[i] - 1] + m_h
  for i in range(len(z_alphas)): abu[z_alphas[i] - 1] = abu[z_alphas[i] - 1] + alpha
  

  atmos = np.zeros(nd, dtype={'names':('dm', 't', 'p','ne'),
                          'formats':('f', 'f', 'f','f')}) 

  atmos['dm'] = f['pgas'] / 10.**logg
  atmos['t'] = f['temp']
  atmos['p'] = f['pgas']
  atmos['ne'] = f['pe']/ bolk / f['temp']

  return (teff,logg,vmicro,abu,nd,atmos)


def read_phoenix_text_model(modelfile):
  
  
  """Reads a plain-text Phoenix model atmospheres
  
  Parameters
  ----------
  modelfile: str
      file name  
  
  Returns
  -------

  teff : float
      effective temperature (K)
  logg : float
      log10 of the surface gravity (cm s-2)
  vmicro : float
      microturbulence velocity (km/s)
  abu : list
      abundances, number densities of nuclei relative to hydrogen N(X)/N(H)
      for elements Z=1,99 (H to Es)
  nd: int
      number of depths (layers) of the model
  atmos: numpy structured array
      array with the run with depth of column mass, temperature, gas pressure 
      and electron density  
  
  """  


  f = open(modelfile,'r')
  line = f.readline()
  while line[0:4] != " no.":
    line = f.readline()
  entries = line.split()
  nd = int(entries[5])
  print('nd=',nd)
  while line[0:14] != " model:   teff":
    line = f.readline()
  entries = line.split()
  teff = float(entries[3])
  print('teff=',teff)
  line = f.readline()
  line = f.readline()
  entries = line.split()
  assert (entries[0] == 'log(g):' and entries[2] == '[cm/s**2]'), 'Cannot find logg in the file header'
  logg = float(entries[1])
  print('logg=',logg)
  line = f.readline()
  while line[0:22] !=  "  Element abundances :":  
    line = f.readline()


  symbol,mass,sol = elements()

  sy = []
  ab = []

  while line[0:29] !=  "  Element abundances relative":  
    line = f.readline()
    #print(line)
    if line[0:9] == ' element:':
      entries = line.split()
      for word in entries[1:]: sy.append(word)
    if line[0:11] == ' abundance:':
      entries = line.split()
      for word in entries[1:]: ab.append(word)

  assert (len(sy) == len(ab)), 'different elements in arrays sy (elemental symbols) and ab (abundances)'

  abu = np.ones(99)*1e-99
  i = 0
  for item in sy:
    try:
      index = symbol.index(item)
      abu[index] =  10.**(float(ab[i])-12.) 
    except ValueError:
      print("the symbol ",item," is not recognized as a valid element")
    i = i + 1

  print('abu=',abu)

  while line[0:72] !=  "   l        tstd temperature        pgas          pe     density      mu":  
    line = f.readline()

  line = f.readline()
  entries = line.split()

  t = [ float(entries[2].replace('D','E')) ]
  p = [ float(entries[3].replace('D','E')) ]
  ne = [ float(entries[4].replace('D','E')) / bolk / float(entries[2].replace('D','E')) ] 
  dm = [ float(entries[3].replace('D','E')) / 10.**logg ] #assuming hydrostatic equil. and negliglible radiation and turb. pressure

  for i in range(nd-1):
    line = f.readline()
    entries = line.split()

    t.append(  float(entries[2].replace('D','E')))
    p.append(  float(entries[3].replace('D','E')))
    ne.append( float(entries[4].replace('D','E')) / bolk / float(entries[2]))
    dm.append ( float(entries[3].replace('D','E')) / 10.**logg )

  vmicro = 0.0
  while (line[0:6] != " greli"):
    line = f.readline()
    if line == '':
        print('Cannot find a value for vmicro (vturb) in the model atmosphere file ',modelfile)
        break
  
  if line != '':
    entries = line.split()
    vmicro = float(entries[5])

  atmos = np.zeros(nd, dtype={'names':('dm', 't', 'p','ne'),
                          'formats':('f', 'f', 'f','f')}) 
  atmos['dm'] = dm
  atmos['t'] = t
  atmos['p'] = p
  atmos['ne'] = ne

  return (teff,logg,vmicro,abu,nd,atmos)


def read_multiline_fltarray(fhandle,arrlen):

  """Reads a float array that spans one or multiple lines in a file
  """

  ndata = 0
  arr = []
  while ndata < arrlen:
    line = fhandle.readline()
    line = line.replace('D','E')
    line = line.replace('d','e')
    entries = line.split()
    for val in entries: arr.append( float(val) )
    ndata = len(arr)

  return (arr)



def interp_spl(xout, x, y):

  """Interpolates in 1D using cubic splines

  Parameters
  ----------
     x: numpy array or list
        input abscissae
     y: numpy array or list
        input ordinates 
     xout: numpy array or list
        array of abscissae to interpolate to

   Returns
   -------
     yout: numpy array or list
        array of interpolated values

  """

  tck = interpolate.splrep(x, y, s=0)
  yout = interpolate.splev(xout, tck, der=0)

  return(yout)



def interp_spl2(x0, x, y):
    """
    Interpolate a 1-D function using cubic splines.
      x0 : a float or an 1d-array
      x : (N,) array_like
          A 1-D array of real/complex values.
      y : (N,) array_like
          A 1-D array of real values. The length of y along the
          interpolation axis must be equal to the length of x.

    Implement a trick to generate at first step the cholesky matrice L of
    the tridiagonal matrice A (thus L is a bidiagonal matrice that
    can be solved in two distinct loops).

    additional ref: www.math.uh.edu/~jingqiu/math4364/spline.pdf 
    
    code from
    https://stackoverflow.com/questions/31543775/how-to-perform-cubic-spline-interpolation-in-python
    """
    x = np.asfarray(x)
    y = np.asfarray(y)

    # remove non finite values
    # indexes = np.isfinite(x)
    # x = x[indexes]
    # y = y[indexes]

    # check if sorted
    if np.any(np.diff(x) < 0):
        indexes = np.argsort(x)
        x = x[indexes]
        y = y[indexes]

    size = len(x)

    xdiff = np.diff(x)
    ydiff = np.diff(y)

    # allocate buffer matrices
    Li = np.empty(size)
    Li_1 = np.empty(size-1)
    z = np.empty(size)

    # fill diagonals Li and Li-1 and solve [L][y] = [B]
    Li[0] = np.sqrt(2*xdiff[0])
    Li_1[0] = 0.0
    B0 = 0.0 # natural boundary
    z[0] = B0 / Li[0]

    for i in range(1, size-1, 1):
        Li_1[i] = xdiff[i-1] / Li[i-1]
        Li[i] = np.sqrt(2*(xdiff[i-1]+xdiff[i]) - Li_1[i-1] * Li_1[i-1])
        Bi = 6*(ydiff[i]/xdiff[i] - ydiff[i-1]/xdiff[i-1])
        z[i] = (Bi - Li_1[i-1]*z[i-1])/Li[i]

    i = size - 1
    Li_1[i-1] = xdiff[-1] / Li[i-1]
    Li[i] = np.sqrt(2*xdiff[-1] - Li_1[i-1] * Li_1[i-1])
    Bi = 0.0 # natural boundary
    z[i] = (Bi - Li_1[i-1]*z[i-1])/Li[i]

    # solve [L.T][x] = [y]
    i = size-1
    z[i] = z[i] / Li[i]
    for i in range(size-2, -1, -1):
        z[i] = (z[i] - Li_1[i-1]*z[i+1])/Li[i]

    # find index
    index = x.searchsorted(x0)
    np.clip(index, 1, size-1, index)

    xi1, xi0 = x[index], x[index-1]
    yi1, yi0 = y[index], y[index-1]
    zi1, zi0 = z[index], z[index-1]
    hi1 = xi1 - xi0

    # calculate cubic
    f0 = zi0/(6*hi1)*(xi1-x0)**3 + \
         zi1/(6*hi1)*(x0-xi0)**3 + \
         (yi1/hi1 - zi1*hi1/6)*(x0-xi0) + \
         (yi0/hi1 - zi0*hi1/6)*(xi1-x0)
    return f0



def elements(husser=False):
  
  """Reads the solar elemental abundances
  
  Parameters
  ----------
     husser: bool, optional
        when set the abundances adopted for Phoenix models by Huser et al. (2013)
        are adopted. Otherwise Asplund et al. (2005) are used -- consistent with
        the MARCS (Gustafsson et al. 2008) models and and Kurucz (Meszaros et al. 2012)
        Kurucz model atmospheres.
        
  Returns
  -------
     symbol: numpy array of str
        element symbols
     mass: numpy array of floats
        atomic masses (elements Z=1-99)
     sol: numpy array of floats
        solar abundances N/N(H)
  
  """

  symbol = [
  'H' ,'He','Li','Be','B' ,'C' ,'N' ,'O' ,'F' ,'Ne', 
  'Na','Mg','Al','Si','P' ,'S' ,'Cl','Ar','K' ,'Ca', 
  'Sc','Ti','V' ,'Cr','Mn','Fe','Co','Ni','Cu','Zn', 
  'Ga','Ge','As','Se','Br','Kr','Rb','Sr','Y' ,'Zr', 
  'Nb','Mo','Tc','Ru','Rh','Pd','Ag','Cd','In','Sn', 
  'Sb','Te','I' ,'Xe','Cs','Ba','La','Ce','Pr','Nd', 
  'Pm','Sm','Eu','Gd','Tb','Dy','Ho','Er','Tm','Yb', 
  'Lu','Hf','Ta','W' ,'Re','Os','Ir','Pt','Au','Hg', 
  'Tl','Pb','Bi','Po','At','Rn','Fr','Ra','Ac','Th', 
  'Pa','U' ,'Np','Pu','Am','Cm','Bk','Cf','Es' ]

  mass = [ 1.00794, 4.00260, 6.941, 9.01218, 10.811, 12.0107, 14.00674, 15.9994,
  18.99840, 20.1797, 22.98977, 24.3050, 26.98154, 28.0855, 30.97376, 
  32.066, 35.4527, 39.948, 39.0983, 40.078, 44.95591, 47.867, 50.9415, 
  51.9961, 54.93805, 55.845, 58.93320, 58.6934, 63.546, 65.39, 69.723, 
  72.61, 74.92160, 78.96, 79.904, 83.80, 85.4678, 87.62, 88.90585, 
  91.224, 92.90638, 95.94, 98., 101.07, 102.90550, 106.42, 107.8682, 
  112.411, 114.818, 118.710, 121.760, 127.60, 126.90447, 131.29, 
  132.90545, 137.327, 138.9055, 140.116, 140.90765, 144.24, 145, 150.36, 
  151.964, 157.25, 158.92534, 162.50, 164.93032, 167.26, 168.93421, 
  173.04, 174.967, 178.49, 180.9479, 183.84, 186.207, 190.23, 192.217, 
  195.078, 196.96655, 200.59, 204.3833, 207.2, 208.98038, 209., 210., 
  222., 223., 226., 227., 232.0381, 231.03588, 238.0289, 237., 244., 
  243., 247., 247., 251., 252. ]

  if not husser:
    #Asplund, Grevesse and Sauval (2005), basically the same as 
    #Grevesse N., Asplund M., Sauval A.J. 2007, Space Science Review 130, 205
    sol = [  0.911, 10.93,  1.05,  1.38,  2.70,  8.39,  7.78,  8.66,  4.56,  7.84, 
    6.17,  7.53,  6.37,  7.51,  5.36,  7.14,  5.50,  6.18,  5.08,  6.31, 
    3.05,  4.90,  4.00,  5.64,  5.39,  7.45,  4.92,  6.23,  4.21,  4.60, 
    2.88,  3.58,  2.29,  3.33,  2.56,  3.28,  2.60,  2.92,  2.21,  2.59, 
    1.42,  1.92, -9.99,  1.84,  1.12,  1.69,  0.94,  1.77,  1.60,  2.00, 
    1.00,  2.19,  1.51,  2.27,  1.07,  2.17,  1.13,  1.58,  0.71,  1.45, 
   -9.99,  1.01,  0.52,  1.12,  0.28,  1.14,  0.51,  0.93,  0.00,  1.08, 
    0.06,  0.88, -0.17,  1.11,  0.23,  1.45,  1.38,  1.64,  1.01,  1.13,
    0.90,  2.00,  0.65, -9.99, -9.99, -9.99, -9.99, -9.99, -9.99,  0.06,   
   -9.99, -0.52, -9.99, -9.99, -9.99, -9.99, -9.99, -9.99, -9.99 ]
	      
    sol[0] = 1.

  else:
    #a combination of meteoritic/photospheric abundances from Asplund et al. 2009
    #chosen for the Husser et al. (2013) Phoenix model atmospheres
    sol = [  12.00, 10.93,  3.26,  1.38,  2.79,  8.43,  7.83,  8.69,  4.56,  7.93, 
    6.24,  7.60,  6.45,  7.51,  5.41,  7.12,  5.50,  6.40,  5.08,  6.34, 
    3.15,  4.95,  3.93,  5.64,  5.43,  7.50,  4.99,  6.22,  4.19,  4.56, 
    3.04,  3.65,  2.30,  3.34,  2.54,  3.25,  2.36,  2.87,  2.21,  2.58, 
    1.46,  1.88, -9.99,  1.75,  1.06,  1.65,  1.20,  1.71,  0.76,  2.04, 
    1.01,  2.18,  1.55,  2.24,  1.08,  2.18,  1.10,  1.58,  0.72,  1.42, 
   -9.99,  0.96,  0.52,  1.07,  0.30,  1.10,  0.48,  0.92,  0.10,  0.92, 
    0.10,  0.85, -0.12,  0.65,  0.26,  1.40,  1.38,  1.62,  0.80,  1.17,
    0.77,  2.04,  0.65, -9.99, -9.99, -9.99, -9.99, -9.99, -9.99,  0.06,   
   -9.99, -0.54, -9.99, -9.99, -9.99, -9.99, -9.99, -9.99, -9.99 ]

  sol[0] = 1.
  for i in range(len(sol)-1): sol[i+1] = 10.**(sol[i+1]-12.0)

  return (symbol,mass,sol)


def lgconv(xinput, yinput, fwhm, ppr=None):

  """convolution with a Gaussian in linear lambda scale
  for a constant resolution

  Parameters
  ----------
  xinput: numpy float array
      wavelengths 
  yinput: numpy array of floats
      fluxes
  fwhm: float
      FWHM of the Gaussian (same units as for xinput)
  ppr: float, optional
      Points per resolution element to downsample the convolved spectrum
      (default None, to keep the original sampling)

  Returns
  -------
  x: numpy float array
      wavelengths after convolution, will be a subset of xinput when that is linear, 
      otherwise a subset of the linearly resampled version
  y: numpy array of floats
      fluxes after convolution

  """

  #resampling to a linear lambda wavelength scale if need be
  xx = np.diff(xinput)
  if max(xx) - min(xx) > 1.e-7: #input not linearly sampled
    nel = len(xinput)
    minx = np.min(xinput)
    maxx = np.max(xinput)
    x = np.linspace(minx,maxx,nel)
    #y = np.interp( x, xinput, yinput)
    y = interp_spl( x, xinput, yinput)
  else:                       #input linearly sampled
    x = xinput
    y = yinput

  step = x[1] - x[0]
  sigma=fwhm/2.0/np.sqrt(-2.0*np.log(0.5))
  npoints = 2*int(3*fwhm/2./step)+1
  half = npoints * step /2.
  xx = np.linspace(-half,half,npoints)
  kernel = np.exp(-(xx-np.mean(xx))**2/2./sigma**2)
  kernel = kernel/np.sum(kernel)

  y = np.convolve(y,kernel,'valid')
  #y = ss.fftconvolve(y,kernel,'valid')
  print(npoints)
  edge = int(npoints/2)
  x = x[edge:-edge]

  print(xinput.size,x.size,y.size)

  if ppr != None:
    fac = int(fwhm / step / ppr)
    subset = np.arange(x.size / fac, dtype=int) * fac 
    x = x[subset]
    y = y[subset]

  return(x,y)

def vgconv(xinput,yinput,fwhm, ppr=None):


  """convolution with a Gaussian in log lambda scale
  for a constant resolving power

  Parameters
  ----------
  xinput: numpy float array
      wavelengths 
  yinput: numpy array of floats
      fluxes
  fwhm: float
      FWHM of the Gaussian (km/s)
  ppr: float, optional
      Points per resolution element to downsample the convolved spectrum
      (default None, to keep the original sampling)

  Returns
  -------
  x: numpy float array
      wavelengths after convolution, will be a subset of xinput when that is equidistant
      in log lambda, otherwise a subset of the resampled version
  y: numpy array of floats
      fluxes after convolution

  """
  #resampling to ln(lambda) if need be
  xx = np.diff(np.log(xinput))
  if max(xx) - min(xx) > 1.e-7:  #input not equidist in loglambda
    nel = len(xinput)
    minx = np.log(xinput[0])
    maxx = np.log(xinput[-1])
    x = np.linspace(minx,maxx,nel)
    step = x[1] - x[0]
    x = np.exp(x)
    #y = np.interp( x, xinput, yinput)
    y = interp_spl( x, xinput, yinput)
  else:
    x = xinput
    y = yinput
    step = np.log(xinput[1])-np.log(xinput[0])

  fwhm = fwhm/clight # inverse of the resolving power
  sigma=fwhm/2.0/np.sqrt(-2.0*np.log(0.5))
  npoints = 2*int(3*fwhm/2./step)+1
  half = npoints * step /2.
  xx = np.linspace(-half,half,npoints)
  kernel = np.exp(-(xx-np.mean(xx))**2/2./sigma**2)
  kernel = kernel/np.sum(kernel)

  y = np.convolve(y,kernel,'valid')
  edge = int(npoints/2)
  x = x[edge:-edge]

  #print(xinput.size,x.size,y.size)

  if ppr != None:
    fac = int(fwhm / step / ppr)
    print(fwhm,step,ppr,fac)
    subset = np.arange(x.size / fac, dtype=int) * fac 
    x = x[subset]
    y = y[subset]


  return(x,y)

def rotconv(xinput,yinput,vsini, ppr=None):


  """convolution with a Rotation profile 

  Parameters
  ----------
  xinput: numpy float array
      wavelengths 
  yinput: numpy array of floats
      fluxes
  vsini: float
      projected rotational velocity (km/s)
  ppr: float, optional
      Points per resolution element to downsample the convolved spectrum
      (default None, to keep the original sampling)

  Returns
  -------
  x: numpy float array
      wavelengths after convolution, will be a subset of xinput when that is equidistant
      in log lambda, otherwise a subset of the resampled version
  y: numpy array of floats
      fluxes after convolution

  """

  #resampling to ln(lambda) if need be
  xx = np.diff(np.log(xinput))
  if max(xx) - min(xx) > 1.e-7:  #input not equidist in loglambda
    nel = len(xinput)
    minx = np.min(np.log(xinput))
    maxx = np.max(np.log(xinput))
    x = np.linspace(minx,maxx,nel)
    step = x[1] - x[0]
    x = np.exp(x)
    #y = np.interp( x, xinput, yinput)
    y = interp_spl( x, xinput, yinput)
  else:
    x = xinput
    y = yinput

  deltamax=vsini/clight
  npoints = 2*int(deltamax/step)+1
  xx = np.linspace(-deltamax,deltamax,npoints)
  c1=2.0*(1.0-epsilon)/np.pi/(1.0-epsilon/3.0)/deltamax
  c2=0.5*epsilon/(1.0-epsilon/3.0)/deltamax
  r2=(xx/deltamax)**2
  kernel = c1*np.sqrt(1.0-r2)+c2*(1.0-r2)
  kernel = kernel/np.sum(kernel)


  y = np.convolve(y,kernel,'valid')
  print(xinput.size,x.size,y.size)
  edge = int(npoints/2)
  x = x[edge:-edge]

  if ppr != None:
    fac = int(deltamax / step / ppr)
    subset = np.arange(x.size / fac, dtype=int) * fac 
    x = x[subset]
    y = y[subset]

  return(x,y)

def gsynth(synthfile,fwhm=0.0,outsynthfile=None,ppr=5,wrange=None,freeze=None):

  """Smooth the spectra in a FERRE grid by Gaussian convolution

  Parameters
  ----------
  synthfile: str
      name of the input FERRE synth file 
  fwhm: float
      FWHM of the Gaussian kernel (km/s)      
      (default is 0.0, which means no convolution is performed)
  outsynthfile: str
      name of the output FERRE synth file
      (default is the same as synth file, but starting with 'n')
  ppr: float, optional
      Points per resolution element to downsample the convolved spectrum
      (default is 5, set to None to keep the original sampling)
  wrange: tuple
      Starting and ending wavelengths (if a smaller range that 
      the input's is desired)
      (default None, to keep the original range)
  freeze: dictionary
      Allows to reduce the dimensionality of the grid. The keys are the labels
      of the dimensions to freeze (as given in in the header of the input grid) 
      with the values that should be adopted for those 'frozen' dimensions. 
      Example: set freeze = {'TEFF': 5000.} to fix that value for the Teff dimension
      in a grid.
      (default None, to retain all the original dimensions)
  Returns
  -------
  writes outsynthfile with the smooth spectra

  """

  if outsynthfile is None: outsynthfile='n'+synthfile[1:]
  logw=0

  #read header, update and write out
  fin = open(synthfile,'r')
  fout = open(outsynthfile,'w')
  hd = []
  labels = []
  line = fin.readline()
  hd.append(line)
  while line[1] != "/":
    line = fin.readline()
    if "N_P" in line: n_p = np.array(line.split()[2:],dtype=int)
    if "STEPS" in line: steps = np.array(line.split()[2:],dtype=float)
    if "LLIMITS" in line: llimits = np.array(line.split()[2:],dtype=float)
    if "LABEL" in line: labels.append(line.split()[-1][1:-1])
    if "NPIX" in line: npix = int(line.split()[2])
    if "N_OF_DIM" in line: ndim = int(line.split()[2])
    if "WAVE" in line: wave = np.array(line.split()[2:],dtype=float)
    if "LOGW" in line: logw = int(line.split()[2]) 
    if "RESOLUTION" in line: resolution = float(line.split()[2])
    hd.append(line)

  assert (len(n_p) == len(steps) & len(n_p) == len(llimits) & len(n_p) == len(labels) & len(n_p) == ndim), 'The dimension of the parameters from the header are inconsistent'

  #update header parameters
  x = np.arange(npix)*wave[1]+wave[0]
  if logw == 1: x=10.**x
  if logw == 2: x=np.exp(x)
  
  #define indices for grid loops
  ll = []
  ind_n_p = []
  i = 0
  for entry in labels:
    if freeze is not None:   
      lfkeys = list(freeze.keys())
      if entry not in lfkeys: ind_n_p.append(i)
    else:
      ind_n_p.append(i)
    ll.append(np.arange(n_p[i]))
    i = i + 1
  ind = list(product(*ll))
  
  if wrange is not None:
    assert (len(wrange) == 2), 'Error: wrange must have two elements'
    section1 = np.where( (x >= wrange[0]*(1.-10.*fwhm/clight)) & (x <= wrange[1]*(1.+10.*fwhm/clight)) )
    x = x[section1]
    npix = len(x)
    
  if fwhm > 1.e-7:
    y = np.ones(npix)
    xx,yy = vgconv(x,y,fwhm,ppr=ppr)
  else:
    print('Warning -- fwhm <= 1.e-7, no convolution will be performed, ppr will be ignored')
    xx = x
  
  print(len(x),len(xx))
  
  if wrange is not None: 
    section2 = np.where( (xx >= wrange[0]) & (xx <= wrange[1]) ) 
    xx = xx [section2]
    
  #print(x,xx)
  #print(len(x),len(xx))
  
  jlabel = 0
  for line in hd:
    if "N_OF_DIM" in line: line = " N_OF_DIM = "+str(len(ind_n_p))+"\n"    
    if "N_P" in line: line = " N_P = "+' '.join(map(str,n_p[ind_n_p]))+"\n"   
    if "STEPS" in line: line = " STEPS = "+' '.join(map(str,steps[ind_n_p]))+"\n"   
    if "LLIMITS" in line: line = " LLIMITS = "+' '.join(map(str,llimits[ind_n_p]))+"\n"
    if freeze is not None:
      if "LABEL" in line:
        ilabel = line.split()[-1][1:-1] #drop starting/ending quotes
        if ilabel in lfkeys:
          continue
        else:
          jlabel = jlabel + 1
          line = " LABEL("+str(jlabel)+") = "+ilabel+"\n"
    if "NPIX" in line: line = " NPIX = "+str(len(xx))+"\n"
    if "WAVE" in line: line = " WAVE = "+str(np.log10(xx[0]))+" "+str(np.log10(xx[1])-np.log10(xx[0]))+"\n"
    if "LOGW" in line: line = " LOGW = 1 \n"
    if "RESOLUTION" in line: line = " RESOLUTION = "+str(clight/np.sqrt(clight**2/resolution**2 + fwhm**2))+"\n"
    fout.write(line)

  #smooth and write data
  k = 0
  j = 0
  ntot = np.prod(n_p)
  for i in ind:
    j = j + 1
    print('line ',j,' of ',ntot)
    #print(k,ntot,i)
    #print(i,steps,llimits)
    par = i*steps+llimits
    line = fin.readline()
    if freeze is not None:
      skip = True
      for entry in lfkeys: 
        if (abs(freeze[entry] - par[labels.index(entry)]) < 1e-6): skip = False
      if skip: continue
    y = np.array(line.split(),dtype=float)
    if wrange is not None: y = y [section1]
    if fwhm > 1.e-7:
      xx,yy = vgconv(x,y,fwhm,ppr=ppr)
    else:
      xx,yy = x, y 
    if wrange is not None: yy = yy[section2]
    yy.tofile(fout,sep=" ",format="%0.4e")
    fout.write("\n")
    k = k + 1

  fin.close()
  fout.close()

if __name__ == "__main__":

  npar = len(sys.argv)
  assert (npar >= 4), 'Synple requires at least 3 input parameters (modelfile wstart wend)'
  assert (npar <= 7), 'Synple requires at maximum 6 input parameters (modelfile wstart wend vmicro vrot fwhm)'
  vmicro = None
  vrot = 0.0
  fwhm = 0.0
  modelfile = sys.argv[1]
  wstart = float(sys.argv[2])
  wend = float(sys.argv[3])
  if (npar > 4): 
    vmicro = float(sys.argv[4])
    if (npar > 5):
      fwhm = float(sys.argv[5])
      if (npar > 6):
        vrot = float(sys.argv[6])

  #symbol, mass, sol = elements()
  x, y, z = syn(modelfile, (wstart,wend), save=True, vmicro=vmicro, vrot=vrot, fwhm=fwhm)


