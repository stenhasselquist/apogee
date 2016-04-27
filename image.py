import numpy as np
from astropy.io import fits
from astropy.io import ascii
from astropy.modeling import models, fitting
from astropy.convolution import convolve, Box1DKernel
import matplotlib.pyplot as plt
import glob
import bz2
import os
import pdb
try: 
    import pyds9
except:
    print 'pyds9 is not available, proceeding'

class BOX() :
    """ 
    Defines BOX class
    """
    def __init__(self,xmin=-1,xmax=-1,ymin=-1,ymax=-1,xr=None, yr=None) :
        if xr is not None :
            self.xmin=xr[0]
            self.xmax=xr[1]
        else :
          self.xmin = xmin
          self.xmax = xmax
        if yr is not None :
            self.ymin=yr[0]
            self.ymax=yr[1]
        else :
          self.ymin = ymin
          self.ymax = xmax

    def set(self,xmin,xmax,ymin,ymax):
        self.xmin = xmin
        self.xmax = xmax
        self.ymin = ymin
        self.ymax = ymax

    def nrow(self):
        return(self.ymax-self.ymin)

    def ncol(self):
        return(self.xmax-self.xmin)

    def show(self):
        print '[{:4d}:{:4d},{:4d}:{:4d}]'.format(self.ymin,self.ymax,self.xmin,self.xmax)

    def mean(self,data):
        return data[self.ymin:self.ymax,self.xmin:self.xmax].mean() 

    def stdev(self,data):
        return data[self.ymin:self.ymax,self.xmin:self.xmax].std() 

    def max(self,data):
        return data[self.ymin:self.ymax,self.xmin:self.xmax].max() 

    def min(self,data):
        return data[self.ymin:self.ymax,self.xmin:self.xmax].min() 

    def median(self,data):
        return np.median(data[self.ymin:self.ymax,self.xmin:self.xmax])

def abx(im,box) :
    """ 
    Returns dictionary with image statistics in box 
    """
    return {'mean': box.mean(im),
            'stdev': box.stdev(im),
            'max': box.max(im),
            'min': box.min(im),
            'peakx': np.unravel_index(im[box.ymin:box.ymax,box.xmin:box.xmax].argmax(),(box.nrow(),box.ncol()))[1]+box.xmin,
            'peaky': np.unravel_index(im[box.ymin:box.ymax,box.xmin:box.xmax].argmax(),(box.nrow(),box.ncol()))[0]+box.ymin}

def gfit(data,xcen,ycen,size=5,sub=True) :
    """ 
    Does gaussian fit to input data given initial xcen,ycen
    """
    g_init=models.Gaussian2D(x_mean=xcen,y_mean=ycen,x_stddev=1,y_stddev=1,amplitude=data[ycen,xcen])+models.Const2D(0.)
    fit=fitting.LevMarLSQFitter()
    #fit=fitting.SLSQPLSQFitter()
    y,x=np.mgrid[ycen-size:ycen+size,xcen-size:xcen+size]
    z=data[ycen-size:ycen+size,xcen-size:xcen+size]
    g=fit(g_init,x,y,z)
    if sub :
        out=data
        out[ycen-size:ycen+size,xcen-size:xcen+size]-=g[0](x,y)
        return out
    return g[0](x,y)+g[1](x,y)

def window(hdu,box) :
    """
    Reduce size of image and header accordingly
    """
    hdu.header['CRVAL1'] = box.xmin
    hdu.header['CRVAL2'] = box.ymin
    hdu.header['NAXIS1'] = box.ncol()
    hdu.header['NAXIS2'] = box.nrow()
    box.show()
    new = fits.PrimaryHDU(hdu.data[box.ymin:box.ymax+1,box.xmin:box.xmax+1],hdu.header)
    return new

def stretch(a,ncol=None,nrow=None) :
    """ 
    Stretches a 1D image into a 2D image along rows or columns 
    """
    if nrow is None and ncol is None :
        print 'Must specify either nrow= or ncol='
        return
    if nrow is not None and ncol is not None :
        print 'Must specify only one of nrow= or ncol='
        return
    if ncol is not None :
        out=np.zeros([a.shape[0],ncol])
        for i in range(ncol) :
            out[:,i]=a
    if nrow is not None :
        out=np.zeros([nrow,a.shape[0]])
        for i in range(nrow) :
            out[i,:]=a
    return out

def __get_cnpix(a) :
    """
    Gets CNPIX cards from HDU a, sets them to 1 if they don't exist
    """
    try:
        cnpix1=a.header['CNPIX1']
    except:
        a.header['CNPIX1']=1
    try:
        cnpix2=a.header['CNPIX2']
    except:
        a.header['CNPIX2']=1

    return a.header['CNPIX1'],a.header['CNPIX2']

def __get_overlap(a,b,dc=0,dr=0,box=None) :
    """
    Returns overlap coordinates from two input HDUs
    """
    
    if box is not None :
        print 'need to implement box=!'
        return
 
    a_cnpix1,a_cnpix2 = __get_cnpix(a)
    b_cnpix1,b_cnpix2 = __get_cnpix(b)

    ixmin = max(a_cnpix1,b_cnpix1+dc)
    iymin = max(a_cnpix2,b_cnpix2+dr)
    ixmax = min(a_cnpix1+a.header['NAXIS1'],b_cnpix1+dc+b.header['NAXIS1'])
    iymax = min(a_cnpix2+a.header['NAXIS2'],b_cnpix2+dr+b.header['NAXIS2'])

    return (iymin-a_cnpix2,iymax-a_cnpix2,ixmin-a_cnpix1,ixmax-a_cnpix1,
           iymin-b_cnpix2-dr,iymax-b_cnpix2-dr,ixmin-b_cnpix1-dc,ixmax-b_cnpix1-dc)

def __check_hdu(a) :
    """
    Checks if input variable is an HDU
    """

    if type(a) is fits.hdu.image.PrimaryHDU :
        return True
    else:
        print 'Input must be HDU type, with header and data!'
        return False

def add(a,b,dc=0,dr=0,box=None) :
    """ 
    Adds b to a, paying attention to CNPIX 
    """
    if __check_hdu(a) is False or __check_hdu(b) is False : return
    ay1,ay2,ax1,ax2,by1,by2,bx1,bx2 = __get_overlap(a,b,dr=dr,dc=dc,box=box)
    a.data[ay1:ay2,ax1:ax2] += b.data[by1:by2,bx1:bx2]

def sub(a,b,dc=0,dr=0,box=None) :
    """ 
    Subracts b from a, paying attention to CNPIX 
    """
    if __check_hdu(a) is False or __check_hdu(b) is False : return
    ay1,ay2,ax1,ax2,by1,by2,bx1,bx2 = __get_overlap(a,b,dr=dr,dc=dc,box=box)
    a.data[ay1:ay2,ax1:ax2] -= b.data[by1:by2,bx1:bx2]

def mul(a,b,dc=0,dr=0,box=None) :
    """ 
    Multiplies b by a, paying attention to CNPIX 
    """
    if __check_hdu(a) is False or __check_hdu(b) is False : return
    ay1,ay2,ax1,ax2,by1,by2,bx1,bx2 = __get_overlap(a,b,dr=dr,dc=dc,box=box)
    a.data[ay1:ay2,ax1:ax2] *= b.data[by1:by2,bx1:bx2]

def div(a,b,dc=0,dr=0,box=None) :
    """ 
    Divides a by b, paying attention to CNPIX 
    """
    if __check_hdu(a) is False or __check_hdu(b) is False : return
    ay1,ay2,ax1,ax2,by1,by2,bx1,bx2 = __get_overlap(a,b,dr=dr,dc=dc,box=box)
    a.data[ay1:ay2,ax1:ax2] /= b.data[by1:by2,bx1:bx2]

def clip(hd,min=None,max=None,vmin=None,vmax=None,box=None) :
    """
    Clipping tasks: sets all values above or below input values to specified values

    Args:
         hd : input HDU

    Keyword args:
         min=  (float) : clip values below min
         vmin= (float) : values to clip min values to. If min= is not given clips values <vmin to vmin
         max=  (float) : clip values above max
         vmax= (float) : values to clip max values to. If max= is not given clips values >vmax to vmax
    """
    if __check_hdu(hd) is False : return
   
    if box is not None :
        print 'need to implement box=!'
        return
 
    if min is not None or vmin is not None :
        if vmin is None: 
            clipval=0
        else :
            clipval=vmin
        if min is None:
            min=vmin
        iy,ix=np.where(hd.data > min)
        hd.data[iy,ix]=clipval

    if max is not None or vmax is not None :
        if vmax is None: 
            clipval=0
        else :
            clipval=vmax
        if max is None:
            max=vmax
        iy,ix=np.where(hd.data > max)
        hd.data[iy,ix]=clipval

def buf(hd) :
    """
    Display information about HDU
    """ 
    if __check_hdu(hd) is False : return

    print '    SC    NC    SR    NR  Exp       Date     Name'
    cnpix1,cnpix2 = __get_cnpix(hd)
    npix1 = hd.header['NAXIS1']
    npix2 = hd.header['NAXIS2']
    print '{:6d}{:6d}{:6d}{:6d}'.format(cnpix1,npix1,cnpix2,npix2)

def rd(file,ext=0) :
    """
    Read files into HDU
    """
    try:
        return fits.open(file)[ext]
    except :
        print 'cannot open file: ', file, ' extension: ', ext

def create(box=None,n=None,nr=None,nc=None,sr=1,sc=1,cr=None,cc=None,const=None) :
    """
    Creates a new HDU
    """
    if box is not None:
        nr=box.nrow()
        nc=box.ncol()
        sc=box.xmin
        sr=box.ymin
    else :
        if nr is None and nc is None :
            try :
                nr=n
                nc=n
            except:
                print 'You must specify either box=, n=, or nr= and nc='
                return
        if cr is not None and cc is not None :
            sr=cr-nr/2
            sc=cc-nr/2
    try :
        im=np.zeros([nr,nc])
    except :
        print 'must specify image size '
        return
    hd=fits.PrimaryHDU(im)
    hd.header['CNPIX1'] = sc
    hd.header['CNPIX2'] = sr
    if const is not None :
        hd.data += const
    return hd
 
