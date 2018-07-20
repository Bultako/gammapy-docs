
# coding: utf-8

# # 3D simulation and fitting
# 
# This tutorial shows how to do a 3D map-based simulation and fit.
# 
# For a tutorial on how to do a 3D map analyse of existing data, see the `analysis_3d` tutorial.
# 
# This can be useful to do a performance / sensitivity study, or to evaluate the capabilities of Gammapy or a given analysis method.
# 
# In Gammapy we currently don't have an event sampler, i.e. unbinned analysis as in ctools is not available. Note that other science tools, e.g. Sherpa for Chandra, also just do binned simulations and analysis like we do here.
# 
# Warning: this is work in progress, several missing pieces: background, PSF, diffuse and point source models, model serialisation.
# 
# We aim to have a first usable version ready and documented here for the Gammapy v0.8 release on May 7, 2018.

# ## Imports and versions

# In[1]:


get_ipython().run_line_magic('matplotlib', 'inline')
import matplotlib.pyplot as plt


# In[2]:


import numpy as np
import astropy.units as u
import tempfile
from astropy.coordinates import SkyCoord, Angle
from gammapy.irf import EffectiveAreaTable2D, EnergyDispersion2D, EnergyDependentMultiGaussPSF, Background3D
from gammapy.maps import WcsGeom, MapAxis, WcsNDMap, Map
from gammapy.spectrum.models import PowerLaw
from gammapy.image.models import SkyGaussian
from gammapy.utils.random import get_random_state
from gammapy.cube import (
    make_map_exposure_true_energy,
    SkyModel,
    MapFit,
    MapEvaluator,
    SourceLibrary,
    PSFKernel,
)


# In[3]:


get_ipython().system('gammapy info --no-envvar --no-dependencies --no-system')


# ## Simulate

# In[4]:


# Load CTA IRFs

def get_irfs():
    filename = '$GAMMAPY_EXTRA/datasets/cta-1dc/caldb/data/cta//1dc/bcf/South_z20_50h/irf_file.fits'
    psf = EnergyDependentMultiGaussPSF.read(filename, hdu='POINT SPREAD FUNCTION')
    aeff = EffectiveAreaTable2D.read(filename, hdu='EFFECTIVE AREA')
    edisp = EnergyDispersion2D.read(filename, hdu='ENERGY DISPERSION')
    bkg = Background3D.read(filename, hdu='BACKGROUND')
    return dict(psf=psf, aeff=aeff, edisp=edisp, bkg=bkg)

irfs = get_irfs()


# In[5]:


import os
os.environ['GAMMAPY_EXTRA']


# In[6]:


# Define sky model to simulate the data
spatial_model = SkyGaussian(
    lon_0='0.2 deg',
    lat_0='0.1 deg',
    sigma='0.5 deg',
)
spectral_model = PowerLaw(
    index=3,
    amplitude='1e-11 cm-2 s-1 TeV-1',
    reference='1 TeV',
)
sky_model = SkyModel(
    spatial_model=spatial_model,
    spectral_model=spectral_model,
)
print(sky_model)


# In[7]:


# Alternatively read the skymodel from an XML file
xml = b'''<?xml version="1.0" encoding="utf-8"?>
    <source_library title="source library">
        <source name="3C 273" type="PointSource">
            <spectrum type="PowerLaw">;i
                <parameter free="1" max="1000.0" min="0.001" name="Prefactor" scale="1e-09" value="10"></parameter>
                <parameter free="1" max="-1.0" min="-5.0" name="Index" scale="1.0" value="-2.1"></parameter>
                <parameter free="0" max="2000.0" min="30.0" name="Scale" scale="1.0" value="100.0"></parameter>
            </spectrum>
            <spatialModel type="SkyDirFunction">
                <parameter free="0" max="360" min="-360" name="RA" scale="1.0" value="187.25"></parameter>
                <parameter free="0" max="90" min="-90" name="DEC" scale="1.0" value="2.17"></parameter>
            </spatialModel>
        </source>
    </source_library>
    '''

#source_library = SourceLibrary.from_xml(xml)
#sky_model = source_library.skymodels[0]
#print(sky_model)


# In[8]:


# Define map geometry
axis = MapAxis.from_edges(
    np.logspace(-1., 1., 10), unit='TeV',
)
geom = WcsGeom.create(
    skydir=(0, 0), binsz=0.02, width=(9, 5),
    coordsys='GAL', axes=[axis],
)


# In[9]:


# Define some observation parameters
# Here we just have a single observation,
# we are not simulating many pointings / observations
pointing = SkyCoord(1, 0.5, unit='deg', frame='galactic')
livetime = 1 * u.hour
offset_max = 2 * u.deg
offset = Angle('2 deg')


# In[10]:


# Compute maps, PSF and EDISP - just as you would for analysis of real data

# Exposure
exposure_map = make_map_exposure_true_energy(
    pointing=pointing, livetime=livetime, aeff=irfs['aeff'],
    ref_geom=geom, offset_max=offset_max,
)

# PSF
psf = irfs['psf'].to_energy_dependent_table_psf(theta=offset)
psf_kernel = PSFKernel.from_table_psf(psf,
                                      geom,
                                      max_radius=1 * u.deg)

# EDISP : TODO
edisp = irfs['edisp'].to_energy_dispersion(offset=offset)

# Background: Assume constant background in FoV
bkg = Map.from_geom(geom)
bkg.quantity = np.ones(bkg.data.shape) * 1e-1


# In[11]:


plt.imshow(exposure_map.data[2,:,:])


# In[12]:


plt.imshow(psf_kernel.psf_kernel_map.data[2,:,:])


# In[13]:


# The idea is that we have this class that can compute `npred`
# maps, i.e. "predicted counts per pixel" given the model and
# the observation infos: exposure, background, PSF and EDISP
evaluator = MapEvaluator(sky_model=sky_model, 
                         exposure=exposure_map,
                         psf=psf_kernel,
                         background=bkg)


# In[14]:


# Accessing and saving a lot of the following maps is for debugging.
# Just for a simulation one doesn't need to store all these things.
#dnde = evaluator.compute_dnde()
#flux = evaluator.compute_flux()

npred = evaluator.compute_npred()
npred_map = WcsNDMap(geom, npred)


# In[15]:


npred_map.sum_over_axes().plot(add_cbar=True)


# In[16]:


# The npred map contains negative values, this is probably a bug in the PSFKernel application
npred[npred<0] = 0


# In[17]:


# This one line is the core of how to simulate data when
# using binned simulation / analysis: you Poisson fluctuate
# npred to obtain simulated observed counts.
# Compute counts as a Poisson fluctuation
rng = get_random_state(42)
counts = rng.poisson(npred)
counts_map = WcsNDMap(geom, counts)


# In[18]:


counts_map.sum_over_axes().plot()


# ## Fit
# 
# Now let's analyse the simulated data.
# Here we just fit it again with the same model we had before, but you could do any analysis you like here, e.g. fit a different model, or do a region-based analysis, ...

# In[19]:


# Define sky model to fit the data
spatial_model = SkyGaussian(
    lon_0='0 deg',
    lat_0='0 deg',
    sigma='1 deg',
)
spectral_model = PowerLaw(
    index=2,
    amplitude='1e-11 cm-2 s-1 TeV-1',
    reference='1 TeV',
)
model = SkyModel(
    spatial_model=spatial_model,
    spectral_model=spectral_model,
)

model.parameters.set_parameter_errors({
    'lon_0': '0.1 deg',
    'lat_0': '0.1 deg',
    'sigma': '0.1 deg',
    'index': '0.1',
    'amplitude': '1e-12 cm-2 s-1 TeV-1',
})

model.parameters['sigma'].parmin = 0


# In[20]:


fit = MapFit(
    model=model.copy(),
    counts=counts_map,
    exposure=exposure_map,
    background=bkg
)

fit.fit()


# In[21]:


print('Start values:\n\n{}\n\n'.format(model.parameters))
print('Fit result:\n\n{}\n\n'.format(fit.model.parameters))

# TODO: 
# print('True values\n{}'.format(get_sky_model().parameters))


# In[22]:


# TODO: show e.g. how to make a residual image


# ## iminuit
# 
# What we have done for now is to write a very thin wrapper for http://iminuit.readthedocs.io/
# as a fitting backend. This is just a prototype, we will improve this interface and
# add other fitting backends (e.g. Sherpa or scipy.optimize or emcee or ...)
# 
# As a power-user, you can access ``fit.iminuit`` and get the full power of what is developed there already.
# E.g. the ``fit.fit()`` call ran ``Minuit.migrad()`` and ``Minuit.hesse()`` in the background, and you have
# access to e.g. the covariance matrix, or can check a likelihood profile, or can run ``Minuit.minos()``
# to compute asymmetric errors or ...

# In[23]:


# Check correlation between model parameters
# As expected in this simple case,
# spatial parameters are uncorrelated,
# but the spectral model amplitude and index are correlated as always
fit.minuit.print_matrix()


# In[24]:


# You can use likelihood profiles to check if your model is
# well constrained or not, and if the fit really converged
fit.minuit.draw_profile('sigma');

