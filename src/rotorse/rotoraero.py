#!/usr/bin/env python
# encoding: utf-8
"""
untitled.py

Created by Andrew Ning on 2013-11-21.
Copyright (c) NREL. All rights reserved.
"""

#!/usr/bin/env python
# encoding: utf-8
"""
rotoraero.py

Created by Andrew Ning on 2013-10-07.
Copyright (c) NREL. All rights reserved.
"""

import numpy as np
from scipy import interpolate
from scipy.optimize import brentq
# from scipy.integrate import quad
from math import pi
from openmdao.main.api import VariableTree, Component, Assembly, Driver
from openmdao.main.datatypes.api import Int, Float, Array, VarTree, Str, List, Slot, Enum, Bool
from openmdao.util.decorators import add_delegate
from openmdao.main.hasparameters import HasParameters
from openmdao.main.hasobjective import HasObjective
# from openmdao.main.hasobjectives import HasObjectives
# from openmdao.main.driver import Run_Once

from ccblade import CCAirfoil, CCBlade as CCBlade_PY
from commonse import cosd


# convert between rotations/minute and radians/second
RPM2RS = pi/30.0
RS2RPM = 30.0/pi


# ---------------------
# Variable Trees
# ---------------------


class VarSpeedMachine(VariableTree):
    """variable speed machines"""

    Vin = Float(units='m/s', desc='cut-in wind speed')
    Vout = Float(units='m/s', desc='cut-out wind speed')
    ratedPower = Float(units='W', desc='rated power')
    minOmega = Float(units='deg', desc='minimum allowed rotor rotation speed')
    maxOmega = Float(units='deg', desc='maximum allowed rotor rotation speed')
    tsr = Float(desc='tip-speed ratio in Region 2 (should be optimized externally)')
    pitch = Float(units='deg', desc='pitch angle in region 2 (and region 3 for fixed pitch machines)')

    def update_outputs(one, two):  # TODO: remove this once vartree bug is fixed.
        pass


class FixedSpeedMachine(VariableTree):
    """fixed speed machines"""

    Vin = Float(units='m/s', desc='cut-in wind speed')
    Vout = Float(units='m/s', desc='cut-out wind speed')
    ratedPower = Float(units='W', desc='rated power')
    Omega = Float(units='rpm', desc='fixed rotor rotation speed')
    pitch = Float(units='deg', desc='pitch angle in region 2 (and region 3 for fixed pitch machines)')



class RatedConditions(VariableTree):
    """aerodynamic conditions at the rated wind speed"""

    V = Float(units='m/s', desc='rated wind speed')
    Omega = Float(units='rpm', desc='rotor rotation speed at rated')
    pitch = Float(units='deg', desc='pitch setting at rated')
    T = Float(units='N', desc='rotor aerodynamic thrust at rated')
    Q = Float(units='N*m', desc='rotor aerodynamic torque at rated')



# ---------------------
# Base Components
# ---------------------

class GeomtrySetupBase(Component):
    """a base component that computes the rotor radius from the geometry"""

    R = Float(iotype='out', units='m', desc='rotor radius')


class AeroBase(Component):
    """A base component for a rotor aerodynamics code."""

    run_case = Enum('power', ('power', 'loads'), iotype='in')


    # --- use these if (run_case == 'power') ---

    # inputs
    Uhub = Array(iotype='in', units='m/s', desc='hub height wind speed')
    Omega = Array(iotype='in', units='rpm', desc='rotor rotation speed')
    pitch = Array(iotype='in', units='deg', desc='blade pitch setting')

    # outputs
    T = Array(iotype='out', units='N', desc='rotor aerodynamic thrust')
    Q = Array(iotype='out', units='N*m', desc='rotor aerodynamic torque')
    P = Array(iotype='out', units='W', desc='rotor aerodynamic power')


    # --- use these if (run_case == 'loads') ---
    # if you only use rotoraero.py and not rotor.py
    # (i.e., only care about power curves, and not structural loads)
    # then these second set of inputs/outputs are not needed

    # inputs
    V_load = Float(iotype='in', units='m/s', desc='hub height wind speed')
    Omega_load = Float(iotype='in', units='rpm', desc='rotor rotation speed')
    pitch_load = Float(iotype='in', units='deg', desc='blade pitch setting')
    azimuth_load = Float(iotype='in', units='deg', desc='blade azimuthal location')

    # outputs
    Px = Array(iotype='out', units='N/m',
        desc='distributed loads in x-direction of blade-aligned coordinate system')
    Py = Array(iotype='out', units='N/m',
        desc='distributed loads in y-direction of blade-aligned coordinate system')
    Pz = Array(iotype='out', units='N/m',
        desc='distributed loads in z-direction of blade-aligned coordinate system')



class DrivetrainLossesBase(Component):
    """base component for drivetrain efficiency losses"""

    aeroPower = Array(iotype='in', units='W', desc='aerodynamic power')
    aeroTorque = Array(iotype='in', units='N*m', desc='aerodynamic torque')
    aeroThrust = Array(iotype='in', units='N', desc='aerodynamic thrust')
    ratedPower = Float(iotype='in', units='W', desc='rated power')

    power = Array(iotype='out', units='W', desc='total power after drivetrain losses')


class PDFBase(Component):
    """probability distribution function"""

    x = Array(iotype='in')

    f = Array(iotype='out')


class CDFBase(Component):
    """cumulative distribution function"""

    x = Array(iotype='in')

    F = Array(iotype='out')




# ---------------------
# Subclassed Components
# ---------------------


class CCBladeGeometry(GeomtrySetupBase):

    Rtip = Float(iotype='in', units='m', desc='tip radius')
    precone = Float(0.0, iotype='in', desc='precone angle', units='deg')

    def execute(self):

        self.R = self.Rtip*cosd(self.precone)



class CCBlade(AeroBase):
    """blade element momentum code"""

    # variables
    r = Array(iotype='in', units='m', desc='radial locations where blade is defined (should be increasing and not go all the way to hub or tip)')
    chord = Array(iotype='in', units='m', desc='chord length at each section')
    theta = Array(iotype='in', units='deg', desc='twist angle at each section (positive decreases angle of attack)')
    Rhub = Float(iotype='in', units='m', desc='hub radius')
    Rtip = Float(iotype='in', units='m', desc='tip radius')
    hubheight = Float(iotype='in', units='m')

    # parameters
    airfoil_files = List(Str, iotype='in', desc='names of airfoil file')
    precone = Float(0.0, iotype='in', desc='precone angle', units='deg')
    tilt = Float(0.0, iotype='in', desc='shaft tilt', units='deg')
    yaw = Float(0.0, iotype='in', desc='yaw error', units='deg')
    B = Int(3, iotype='in', desc='number of blades')
    rho = Float(1.225, iotype='in', units='kg/m**3', desc='density of air')
    mu = Float(1.81206e-5, iotype='in', units='kg/m/s', desc='dynamic viscosity of air')
    shearExp = Float(0.2, iotype='in', desc='shear exponent')
    nSector = Int(4, iotype='in', desc='number of sectors to divide rotor face into in computing thrust and power')


    def execute(self):

        # airfoil files
        n = len(self.airfoil_files)
        af = [0]*n
        afinit = CCAirfoil.initFromAerodynFile
        for i in range(n):
            af[i] = afinit(self.airfoil_files[i])

        ccblade = CCBlade_PY(self.r, self.chord, self.theta, af, self.Rhub, self.Rtip, self.B,
            self.rho, self.mu, self.precone, self.tilt, self.yaw, self.shearExp, self.hubheight,
            self.nSector, derivatives=True)

        run_case = self.run_case

        if run_case == 'power':

            # power, thrust, torque
            P, T, Q, dP_ds, dT_ds, dQ_ds, dP_dv, dT_dv, dQ_dv \
                = ccblade.evaluate(self.Uhub, self.Omega, self.pitch, coefficient=False)

            self.P = P
            self.T = T
            self.Q = Q


        if run_case == 'loads':

            # distributed loads

            if self.Omega_load == 0.0:  # TODO: implement derivatives for this case
                Np, Tp = ccblade.distributedAeroLoads(self.V_load, self.Omega_load, self.pitch_load, self.azimuth_load)
            else:
                Np, Tp, dNp_dX, dTp_dX, dNp_dprecurve, dTp_dprecurve \
                    = ccblade.distributedAeroLoads(self.V_load, self.Omega_load, self.pitch_load, self.azimuth_load)

            self.Np = Np
            self.Tp = Tp



class CSMDrivetrain(DrivetrainLossesBase):
    """drivetrain losses from NREL cost and scaling model"""

    drivetrainType = Enum('geared', ('geared', 'single_stage', 'multi_drive', 'pm_direct_drive'), iotype='in')


    def execute(self):

        drivetrainType = self.drivetrainType

        if drivetrainType == 'geared':
            constant = 0.01289
            linear = 0.08510
            quadratic = 0.0

        elif drivetrainType == 'single_stage':
            constant = 0.01331
            linear = 0.03655
            quadratic = 0.06107

        elif drivetrainType == 'multi_drive':
            constant = 0.01547
            linear = 0.04463
            quadratic = 0.05790

        elif drivetrainType == 'pm_direct_drive':
            constant = 0.01007
            linear = 0.02000
            quadratic = 0.06899

        Pbar = self.aeroPower / self.ratedPower

        # TODO: think about these gradients.  may not be able to use abs and minimum

        # handle negative power case
        Pbar = np.abs(Pbar)

        # truncate idealized power curve for purposes of efficiency calculation
        Pbar = np.minimum(Pbar, 1.0)

        # compute efficiency
        eff = np.zeros_like(Pbar)
        idx = Pbar != 0

        eff[idx] = 1.0 - (constant/Pbar[idx] + linear + quadratic*Pbar[idx])

        self.power = self.aeroPower * eff



class WeibullCDF(CDFBase):
    """Weibull cumulative distribution function"""

    A = Float(iotype='in', desc='scale factor')
    k = Float(iotype='in', desc='shape or form factor')

    def execute(self):

        self.F = 1.0 - np.exp(-(self.x/self.A)**self.k)


class RayleighCDF(CDFBase):
    """Rayleigh cumulative distribution function"""

    xbar = Float(iotype='in', desc='mean value of distribution')

    def execute(self):

        self.F = 1.0 - np.exp(-pi/4.0*(self.x/self.xbar)**2)



# ---------------------
# Components
# ---------------------

class Coefficients(Component):
    """convert power, thrust, torque into nondimensional coefficient form"""

    # inputs
    V = Array(iotype='in', units='m/s', desc='wind speed')
    T = Array(iotype='in', units='N', desc='rotor aerodynamic thrust')
    Q = Array(iotype='in', units='N*m', desc='rotor aerodynamic torque')
    P = Array(iotype='in', units='W', desc='rotor aerodynamic power')

    # inputs used in normalization
    R = Float(iotype='in', units='m', desc='rotor radius')
    rho = Float(iotype='in', units='kg/m**3', desc='density of fluid')


    # outputs
    CT = Array(iotype='out', desc='rotor aerodynamic thrust')
    CQ = Array(iotype='out', desc='rotor aerodynamic torque')
    CP = Array(iotype='out', desc='rotor aerodynamic power')


    def execute(self):

        q = 0.5 * self.rho * self.V**2
        A = pi * self.R**2
        self.CP = self.P / (q * A * self.V)
        self.CT = self.T / (q * A)
        self.CQ = self.Q / (q * self.R * A)




class SetupTSRFixedSpeed(Component):
    """find min and max tsr for a fixed speed machine"""

    # inputs
    R = Float(iotype='in', units='m', desc='rotor radius')
    control = VarTree(FixedSpeedMachine(), iotype='in')

    # outputs
    tsr_min = Float(iotype='out', desc='minimum tip speed ratio')
    tsr_max = Float(iotype='out', desc='maximum tip speed ratio')


    def execute(self):

        ctrl = self.control

        self.tsr_max = ctrl.Omega*RPM2RS*self.R/ctrl.Vin
        self.tsr_min = ctrl.Omega*RPM2RS*self.R/ctrl.Vout




class SetupTSRVarSpeed(Component):
    """find min and max tsr for a variable speed machine"""

    # inputs
    R = Float(iotype='in', units='m', desc='rotor radius')
    control = VarTree(VarSpeedMachine(), iotype='in')

    # outputs
    tsr_min = Float(iotype='out', desc='minimum tip speed ratio')
    tsr_max = Float(iotype='out', desc='maximum tip speed ratio')
    Omega_nominal = Float(iotype='out', units='rpm', desc='a nominal rotation speed to use in tsr sweep')


    def execute(self):

        ctrl = self.control
        R = self.R

        # at Vin
        tsr_low_Vin = ctrl.minOmega*RPM2RS*R/ctrl.Vin
        tsr_high_Vin = ctrl.maxOmega*RPM2RS*R/ctrl.Vin

        self.tsr_max = min(max(ctrl.tsr, tsr_low_Vin), tsr_high_Vin)

        # at Vout
        tsr_low_Vout = ctrl.minOmega*RPM2RS*R/ctrl.Vout
        tsr_high_Vout = ctrl.maxOmega*RPM2RS*R/ctrl.Vout

        self.tsr_min = max(min(ctrl.tsr, tsr_high_Vout), tsr_low_Vout)

        # a nominal rotation speed to use for this tip speed ratio (small Reynolds number effect)
        self.Omega_nominal = 0.5*(ctrl.maxOmega + ctrl.minOmega)





class SetupSweep(Component):
    """setup input conditions to AeroBase for a tsr sweep"""

    # inputs
    tsr_min = Float(iotype='in', desc='minimum tip speed ratio')
    tsr_max = Float(iotype='in', desc='maximum tip speed ratio')
    step_size = Float(0.25, iotype='in', desc='step size in tip-speed ratio for sweep (if necessary)')
    Omega_fixed = Float(iotype='in', units='rpm', desc='constant rotation speed used during tsr sweep')
    pitch_fixed = Float(iotype='in', units='deg', desc='set pitch angle')
    R = Float(iotype='in', units='m', desc='rotor radius')

    # outputs
    tsr = Array(iotype='out', desc='array of tip-speed ratios to run AeroBase at')
    Uinf = Array(iotype='out', units='m/s', desc='array of freestream velocities to run AeroBase at')
    Omega = Array(iotype='out', units='rpm', desc='array of rotation speeds to run AeroBase at')
    pitch = Array(iotype='out', units='deg', desc='array of pitch angles to run AeroBase at')


    def execute(self):

        # TODO: rethink this for gradients.  may need to use a fixed n even though some efficiency is lost

        n = int(round((self.tsr_max - self.tsr_min)/self.step_size))
        n = max(n, 1)

        # compute nominal power curve
        self.tsr = np.linspace(self.tsr_min, self.tsr_max, n)
        self.Omega = self.Omega_fixed*np.ones(n)
        self.pitch = self.pitch_fixed*np.ones(n)
        self.Uinf = self.Omega*RPM2RS*self.R/self.tsr




class AeroPowerCurveVarSpeed(Component):
    """create aerodynamic power curve for variable speed machines (no drivetrain losses, no regulation)"""

    # inputs
    tsr_array = Array(iotype='in', desc='tip speed ratios for nondimensional power curve')
    CP_array = Array(iotype='in', desc='corresponding power coefficients for nondimensional power curve')
    CT_array = Array(iotype='in', desc='corresponding thrust coefficients')
    control = VarTree(VarSpeedMachine(), iotype='in')
    R = Float(iotype='in', units='m', desc='rotor radius')
    rho = Float(1.225, iotype='in', units='kg/m**3', desc='density of air')
    npts = Int(200, iotype='in', desc='number of points to generate power curve at (nondimensional power curve is sampled with a sample so a large number is not expensive)')

    # outputs
    V = Array(iotype='out', units='m/s', desc='aerodynamic power curve (wind speeds)')
    Omega = Array(iotype='out', units='rpm', desc='rotation speed curve')
    P = Array(iotype='out', units='W', desc='aerodynamic power curve (corresponding power)')
    T = Array(iotype='out', units='N', desc='thrust curve')
    Q = Array(iotype='out', units='N*m', desc='torque curve')


    def execute(self):

        R = self.R
        ctrl = self.control


        # evaluate from cut-in to cut-out
        V = np.linspace(ctrl.Vin, ctrl.Vout, self.npts)

        # evalaute nondimensional power curve using a spline
        if len(self.tsr_array) == 1:
            cp = self.CP_array[0]
            ct = self.CT_array[0]
            self.Omega = V*self.tsr_array[0]/R

        else:
            tsr = ctrl.tsr*np.ones(len(V))
            min_tsr = ctrl.minOmega*RPM2RS*R/V
            max_tsr = ctrl.maxOmega*RPM2RS*R/V
            tsr = np.minimum(np.maximum(tsr, min_tsr), max_tsr)

            self.Omega = V*tsr/R

            spline = interpolate.interp1d(self.tsr_array, self.CP_array, kind='cubic')
            cp = spline(tsr)

            spline = interpolate.interp1d(self.tsr_array, self.CT_array, kind='cubic')
            ct = spline(tsr)

        # convert to dimensional form
        self.V = V
        self.P = cp * 0.5*self.rho*V**3 * pi*R**2
        self.T = ct * 0.5*self.rho*V**2 * pi*R**2
        self.Q = self.P / self.Omega
        self.Omega *= RS2RPM




class AeroPowerCurveFixedSpeed(Component):
    """create aerodynamic power curve for fixed speed machines (no drivetrain losses, no regulation)"""

    # inputs
    tsr_array = Array(iotype='in', desc='tip speed ratios for nondimensional power curve')
    cp_array = Array(iotype='in', desc='corresponding power coefficients for nondimensional power curve')
    control = VarTree(FixedSpeedMachine(), iotype='in')
    R = Float(iotype='in', units='m', desc='rotor radius')
    rho = Float(1.225, iotype='in', units='kg/m**3', desc='density of air')
    npts = Int(200, iotype='in', desc='number of points to generate power curve at (nondimensional power curve is sampled with a sample so a large number is not expensive)')

    # outputs
    V = Array(iotype='out', units='m/s', desc='aerodynamic power curve (wind speeds)')
    P = Array(iotype='out', units='W', desc='aerodynamic power curve (corresponding power)')


    def execute(self):

        R = self.R
        ctrl = self.control

        # evaluate from cut-in to cut-out
        V = np.linspace(ctrl.Vin, ctrl.Vout, self.npts)
        tsr = ctrl.Omega*RPM2RS*R/V

        spline = interpolate.interp1d(self.tsr_array, self.cp_array, kind='cubic')
        cp = spline(tsr)

        # convert to dimensional form
        self.V = V
        self.P = cp * 0.5*self.rho*V**3 * pi*R**2



class RegulatedPowerCurve(Component):
    """power curve after drivetrain efficiency losses and control regulation"""

    # inputs
    V = Array(iotype='in', units='m/s', desc='wind speeds')
    P0 = Array(iotype='in', units='W', desc='unregulated power curve (but after drivetrain losses)')
    ratedPower = Float(iotype='in', units='W', desc='rated power')

    # outputs
    ratedSpeed = Float(iotype='out', units='m/s', desc='rated speed (if regulated) otherwise speed for max power')
    P = Array(iotype='out', units='W', desc='power curve (power)')

    def execute(self):

        self.P = np.copy(self.P0)

        # find rated speed
        idx = np.argmax(self.P)

        if (self.P[idx] <= self.ratedPower):  # check if rated power not reached
            self.ratedSpeed = self.V[idx]  # no rated speed, but provide max power as we use rated speed as a "worst case"

        else:  # apply control regulation
            self.ratedSpeed = np.interp(self.ratedPower, self.P[:idx], self.V[:idx])
            self.P[self.V > self.ratedSpeed] = self.ratedPower



class AEP(Component):
    """annual energy production"""

    # inputs
    CDF_V = Array(iotype='in')
    P = Array(iotype='in', units='W', desc='power curve (power)')
    lossFactor = Float(iotype='in', desc='multiplicative factor for availability and other losses (soiling, array, etc.)')

    # outputs
    AEP = Float(iotype='out', units='kW*h', desc='annual energy production')


    def execute(self):

        self.AEP = self.lossFactor*np.trapz(self.P/1e3, self.CDF_V*365.0*24.0)  # in kWh



class SetupRatedConditionsVarSpeed(Component):
    """setup to run AeroBase at rated conditions for a variable speed machine"""

    # inputs
    ratedSpeed = Float(iotype='in', units='m/s', desc='rated speed (if regulated) otherwise speed for max power')
    control = VarTree(VarSpeedMachine(), iotype='in')
    R = Float(iotype='in', units='m', desc='rotor radius')

    # outputs (1D arrays because AeroBase expects Array input)
    V_rated = Array(np.zeros(1), iotype='out', shape=((1,)), units='m/s', desc='rated speed')
    Omega_rated = Array(np.zeros(1), iotype='out', shape=((1,)), units='rpm', desc='rotation speed at rated')
    pitch_rated = Array(np.zeros(1), iotype='out', shape=((1,)), units='deg', desc='pitch setting at rated')


    def execute(self):

        ctrl = self.control

        self.V_rated = np.array([self.ratedSpeed])
        self.Omega_rated = np.array([min(ctrl.maxOmega, self.ratedSpeed*ctrl.tsr/self.R*RS2RPM)])
        self.pitch_rated = np.array([ctrl.pitch])


# class SaveRatedConditions(Component):

#     V_rated = Array(iotype='in')
#     Omega_rated = Array(iotype='in')
#     pitch_rated = Array(iotype='in')
#     T_rated = Array(iotype='in')
#     Q_rated = Array(iotype='in')

#     rated = VarTree(RatedConditions(), iotype='out')

#     def execute(self):

#         self.rated.V = self.V_rated[0]
#         self.rated.Omega = self.Omega_rated[0]
#         self.rated.pitch = self.pitch_rated[0]
#         self.rated.T = self.T_rated[0]
#         self.rated.Q = self.Q_rated[0]



# ---------------------
# Assemblies
# ---------------------




class RotorAeroVS(Assembly):

    # --- inputs ---
    rho = Float(1.225, iotype='in', units='kg/m**3', desc='density of air')
    control = VarTree(VarSpeedMachine(), iotype='in')

    # options
    tsr_sweep_step_size = Float(0.25, iotype='in', desc='step size in tip-speed ratio for sweep (if necessary)')
    npts_power_curve = Int(200, iotype='in', desc='number of points to generate power curve at (nondimensional power curve is sampled with a sample so a large number is not expensive)')
    AEP_loss_factor = Float(1.0, iotype='in', desc='availability and other losses (soiling, array, etc.)')


    # --- slots (must replace) ---
    geom = Slot(GeomtrySetupBase)
    analysis = Slot(AeroBase)
    analysis2 = Slot(AeroBase)  # figure out how to replace both at same time
    dt = Slot(DrivetrainLossesBase)
    cdf = Slot(CDFBase)

    # --- outputs ---
    AEP = Float(iotype='out', units='kW*h', desc='annual energy production')
    V = Array(iotype='out', units='m/s', desc='wind speeds (power curve)')
    P = Array(iotype='out', units='W', desc='power (power curve)')
    rated = VarTree(RatedConditions(), iotype='out')


    # # TODO: replace is broken for custom drivers.  remove these later

    # # analysis variables
    # r = Array(iotype='in', units='m', desc='radial locations where blade is defined (should be increasing and not go all the way to hub or tip)')
    # chord = Array(iotype='in', units='m', desc='chord length at each section')
    # theta = Array(iotype='in', units='deg', desc='twist angle at each section (positive decreases angle of attack)')
    # Rhub = Float(iotype='in', units='m', desc='hub radius')
    # Rtip = Float(iotype='in', units='m', desc='tip radius')
    # hubheight = Float(iotype='in', units='m')
    # airfoil_files = List(Str, iotype='in', desc='names of airfoil file')
    # precone = Float(0.0, iotype='in', desc='precone angle', units='deg')
    # tilt = Float(0.0, iotype='in', desc='shaft tilt', units='deg')
    # yaw = Float(0.0, iotype='in', desc='yaw error', units='deg')
    # B = Int(3, iotype='in', desc='number of blades')
    # rho = Float(1.225, iotype='in', units='kg/m**3', desc='density of air')
    # mu = Float(1.81206e-5, iotype='in', units='kg/m/s', desc='dynamic viscosity of air')
    # shearExp = Float(0.2, iotype='in', desc='shear exponent')
    # nSector = Int(4, iotype='in', desc='number of sectors to divide rotor face into in computing thrust and power')

    # drivetrainType = Enum('geared', ('geared', 'single_stage', 'multi_drive', 'pm_direct_drive'), iotype='in')
    # Ubar = Float(iotype='in', desc='mean wind speed of distribution')


    def replace(self, name, obj):

        if name == 'analysis2':
            obj.T = np.zeros(1)
            obj.Q = np.zeros(1)

        super(RotorAeroVS, self).replace(name, obj)

    def configure(self):

        self.add('geom', GeomtrySetupBase())
        self.add('setuptsr', SetupTSRVarSpeed())
        self.add('sweep', SetupSweep())
        self.add('analysis', AeroBase())
        self.add('coeff', Coefficients())
        self.add('aeroPC', AeroPowerCurveVarSpeed())
        self.add('dt', DrivetrainLossesBase())
        self.add('powercurve', RegulatedPowerCurve())
        self.add('cdf', CDFBase())
        self.add('aep', AEP())
        self.add('rated_pre', SetupRatedConditionsVarSpeed())
        self.add('analysis2', AeroBase())

        self.driver.workflow.add(['geom', 'setuptsr', 'sweep', 'analysis', 'coeff',
            'aeroPC', 'dt', 'powercurve', 'cdf', 'aep', 'rated_pre', 'analysis2'])

        # connections to setuptsr
        self.connect('control', 'setuptsr.control')
        self.connect('geom.R', 'setuptsr.R')

        # connections to sweep
        self.connect('setuptsr.tsr_min', 'sweep.tsr_min')
        self.connect('setuptsr.tsr_max', 'sweep.tsr_max')
        self.connect('setuptsr.Omega_nominal', 'sweep.Omega_fixed')
        self.connect('control.pitch', 'sweep.pitch_fixed')
        self.connect('geom.R', 'sweep.R')
        self.connect('tsr_sweep_step_size', 'sweep.step_size')

        # connections to analysis
        self.connect('sweep.Uinf', 'analysis.Uhub')
        self.connect('sweep.Omega', 'analysis.Omega')
        self.connect('sweep.pitch', 'analysis.pitch')
        self.analysis.run_case = 'power'

        # connections to coefficients
        self.connect('sweep.Uinf', 'coeff.V')
        self.connect('analysis.T', 'coeff.T')
        self.connect('analysis.Q', 'coeff.Q')
        self.connect('analysis.P', 'coeff.P')
        self.connect('geom.R', 'coeff.R')
        self.connect('rho', 'coeff.rho')

        # connections to aeroPC
        self.connect('sweep.tsr', 'aeroPC.tsr_array')
        self.connect('coeff.CP', 'aeroPC.CP_array')
        self.connect('coeff.CT', 'aeroPC.CT_array')
        self.connect('control', 'aeroPC.control')
        self.connect('geom.R', 'aeroPC.R')
        self.connect('rho', 'aeroPC.rho')
        self.connect('npts_power_curve', 'aeroPC.npts')

        # connections to drivetrain
        self.connect('aeroPC.P', 'dt.aeroPower')
        self.connect('aeroPC.Q', 'dt.aeroTorque')
        self.connect('aeroPC.T', 'dt.aeroThrust')
        self.connect('control.ratedPower', 'dt.ratedPower')

        # connections to powercurve
        self.connect('aeroPC.V', 'powercurve.V')
        self.connect('dt.power', 'powercurve.P0')
        self.connect('control.ratedPower', 'powercurve.ratedPower')

        # connections to cdf
        self.connect('aeroPC.V', 'cdf.x')

        # connections to aep
        self.connect('cdf.F', 'aep.CDF_V')
        self.connect('powercurve.P', 'aep.P')
        self.connect('AEP_loss_factor', 'aep.lossFactor')

        # connections to rated_pre
        self.connect('powercurve.ratedSpeed', 'rated_pre.ratedSpeed')
        self.connect('control', 'rated_pre.control')
        self.connect('geom.R', 'rated_pre.R')

        # connections to analysis2
        self.connect('rated_pre.V_rated', 'analysis2.Uhub')
        self.connect('rated_pre.Omega_rated', 'analysis2.Omega')
        self.connect('rated_pre.pitch_rated', 'analysis2.pitch')
        self.analysis2.run_case = 'power'
        self.analysis2.T = np.zeros(1)
        self.analysis2.Q = np.zeros(1)

        # connections to outputs
        self.connect('aeroPC.V', 'V')
        self.connect('powercurve.P', 'P')
        self.connect('aep.AEP', 'AEP')
        self.connect('rated_pre.V_rated[0]', 'rated.V')
        self.connect('rated_pre.Omega_rated[0]', 'rated.Omega')
        self.connect('rated_pre.pitch_rated[0]', 'rated.pitch')
        self.connect('analysis2.T[0]', 'rated.T')
        self.connect('analysis2.Q[0]', 'rated.Q')





        # # TODO: remove later
        # self.connect('r', 'analysis.r')
        # self.connect('chord', 'analysis.chord')
        # self.connect('theta', 'analysis.theta')
        # self.connect('Rhub', 'analysis.Rhub')
        # self.connect('Rtip', 'analysis.Rtip')
        # self.connect('hubheight', 'analysis.hubheight')
        # self.connect('airfoil_files', 'analysis.airfoil_files')
        # self.connect('precone', 'analysis.precone')
        # self.connect('tilt', 'analysis.tilt')
        # self.connect('yaw', 'analysis.yaw')
        # self.connect('B', 'analysis.B')
        # self.connect('rho', 'analysis.rho')
        # self.connect('mu', 'analysis.mu')
        # self.connect('shearExp', 'analysis.shearExp')
        # self.connect('nSector', 'analysis.nSector')
        # self.connect('drivetrainType', 'dt.drivetrainType')
        # self.connect('Ubar', 'cdf.Ubar')
        # self.connect('r', 'analysis2.r')
        # self.connect('chord', 'analysis2.chord')
        # self.connect('theta', 'analysis2.theta')
        # self.connect('Rhub', 'analysis2.Rhub')
        # self.connect('Rtip', 'analysis2.Rtip')
        # self.connect('hubheight', 'analysis2.hubheight')
        # self.connect('airfoil_files', 'analysis2.airfoil_files')
        # self.connect('precone', 'analysis2.precone')
        # self.connect('tilt', 'analysis2.tilt')
        # self.connect('yaw', 'analysis2.yaw')
        # self.connect('B', 'analysis2.B')
        # self.connect('rho', 'analysis2.rho')
        # self.connect('mu', 'analysis2.mu')
        # self.connect('shearExp', 'analysis2.shearExp')
        # self.connect('nSector', 'analysis2.nSector')



# --------------------
# Not using right now
# ---------------------




class SetupPitchSearchVS(Component):

    control = VarTree(VarSpeedMachine(), iotype='in')

    R = Float(iotype='in', units='m', desc='rotor radius')
    ratedSpeed = Float(iotype='in', units='m/s', desc='rated speed (if regulated) otherwise speed for max power')

    Omega = Float(iotype='out')
    pitch_min = Float(iotype='out')
    pitch_max = Float(iotype='out')

    def execute(self):

        ctrl = self.control
        self.Omega = min(ctrl.maxOmega, self.ratedSpeed*ctrl.tsr/self.R*RS2RPM)

        # pitch to feather
        self.pitch_min = ctrl.pitch
        self.pitch_max = 40.0


@add_delegate(HasParameters, HasObjective)
class Brent(Driver):
    """root finding using Brent's method."""

    fstar = Float(0.0, iotype='in', desc='function value sought (i.e., find root of f-fstar)')
    xlow = Float(iotype='in')
    xhigh = Float(iotype='in')

    xstar = Float(iotype='out', desc='value sought.  find xstar s.t. f(xstar) = 0')


    def eval(self, x):
        """evaluate f(x)"""

        self.set_parameter_by_name('x', x)
        self.run_iteration()
        obj = self.get_objectives()
        f = obj['f'].evaluate(self.parent)

        return f


    def _error(self, x):
        """solve: f - fstar = 0"""

        f = self.eval(x)

        return f - self.fstar


    def execute(self):

        # bounds
        # params = self.get_parameters()
        # xlow = params['x'].low
        # xhigh = params['x'].high
        xlow = self.xlow
        xhigh = self.xhigh

        # TODO: better error handling.  ideally, if this failed we would attempt to find
        # bounds ourselves rather than throwing an error or returning a value at the bounds
        if self.eval(xlow)*self.eval(xhigh) > 0:
            raise Exception('bounds do not bracket a root')

        # Brent's method
        xstar = brentq(self._error, xlow, xhigh)

        # set result
        self.set_parameter_by_name('x', xstar)
        self.xstar = xstar




class RotorAeroVSVP(RotorAeroVS):

    V_load = Float(iotype='in')
    azimuth_load = Float(iotype='in')

    def configure(self):
        super(RotorAeroVSVP, self).configure()

        # --- residual workflow ---

        self.add('setuppitch', SetupPitchSearchVS())
        # self.add('analysis3', AeroBase())  # TODO: replace back later
        # self.add('dt2', DrivetrainLossesBase())
        self.add('analysis3', CCBlade())
        self.add('dt2', CSMDrivetrain())
        self.add('brent', Brent())

        # connections to setuppitch
        self.connect('control', 'setuppitch.control')
        self.connect('R', 'setuppitch.R')
        self.connect('powercurve.ratedSpeed', 'setuppitch.ratedSpeed')

        # connections to analysis3
        self.analysis3.Uhub = np.zeros(1)
        self.analysis3.Omega = np.zeros(1)
        self.analysis3.pitch = np.zeros(1)
        self.analysis3.run_case = 'power'
        self.connect('V_load', 'analysis3.Uhub[0]')
        self.connect('setuppitch.Omega', 'analysis3.Omega[0]')
        self.brent.add_parameter('analysis3.pitch[0]', name='x', low=0.0, high=40.0)

        # connections to drivetrain
        self.connect('analysis3.P', 'dt2.aeroPower')
        self.connect('control.ratedPower', 'dt2.ratedPower')

        # brent setup
        self.brent.workflow.add(['setuppitch', 'analysis3', 'dt2'])
        self.brent.add_objective('dt2.power[0]', name='f')
        self.connect('control.ratedPower', 'brent.fstar')
        self.connect('setuppitch.pitch_min', 'brent.xlow')
        self.connect('setuppitch.pitch_max', 'brent.xhigh')


        # --- functional workflow ---

        # self.add('analysis4', AeroBase())  TODO
        self.add('analysis4', CCBlade())

        self.driver.workflow.add(['brent', 'analysis4'])

        # connections to analysis4
        self.analysis4.run_case = 'loads'
        self.connect('V_load', 'analysis4.V_load')
        self.connect('setuppitch.Omega', 'analysis4.Omega_load')
        self.connect('brent.xstar', 'analysis4.pitch_load')
        self.connect('azimuth_load', 'analysis4.azimuth_load')

        self.create_passthrough('analysis4.Np')
        self.create_passthrough('analysis4.Tp')




        # TODO: remove later
        self.connect('r', 'analysis3.r')
        self.connect('chord', 'analysis3.chord')
        self.connect('theta', 'analysis3.theta')
        self.connect('Rhub', 'analysis3.Rhub')
        self.connect('Rtip', 'analysis3.Rtip')
        self.connect('hubheight', 'analysis3.hubheight')
        self.connect('airfoil_files', 'analysis3.airfoil_files')
        self.connect('precone', 'analysis3.precone')
        self.connect('tilt', 'analysis3.tilt')
        self.connect('yaw', 'analysis3.yaw')
        self.connect('B', 'analysis3.B')
        self.connect('rho', 'analysis3.rho')
        self.connect('mu', 'analysis3.mu')
        self.connect('shearExp', 'analysis3.shearExp')
        self.connect('nSector', 'analysis3.nSector')
        self.connect('drivetrainType', 'dt2.drivetrainType')
        self.connect('r', 'analysis4.r')
        self.connect('chord', 'analysis4.chord')
        self.connect('theta', 'analysis4.theta')
        self.connect('Rhub', 'analysis4.Rhub')
        self.connect('Rtip', 'analysis4.Rtip')
        self.connect('hubheight', 'analysis4.hubheight')
        self.connect('airfoil_files', 'analysis4.airfoil_files')
        self.connect('precone', 'analysis4.precone')
        self.connect('tilt', 'analysis4.tilt')
        self.connect('yaw', 'analysis4.yaw')
        self.connect('B', 'analysis4.B')
        self.connect('rho', 'analysis4.rho')
        self.connect('mu', 'analysis4.mu')
        self.connect('shearExp', 'analysis4.shearExp')
        self.connect('nSector', 'analysis4.nSector')






if __name__ == '__main__':

    # ---------- inputs ---------------

    # geometry
    r = np.array([2.8667, 5.6000, 8.3333, 11.7500, 15.8500, 19.9500, 24.0500,
                  28.1500, 32.2500, 36.3500, 40.4500, 44.5500, 48.6500, 52.7500,
                  56.1667, 58.9000, 61.6333])
    chord = np.array([3.542, 3.854, 4.167, 4.557, 4.652, 4.458, 4.249, 4.007, 3.748,
                      3.502, 3.256, 3.010, 2.764, 2.518, 2.313, 2.086, 1.419])
    theta = np.array([13.308, 13.308, 13.308, 13.308, 11.480, 10.162, 9.011, 7.795,
                      6.544, 5.361, 4.188, 3.125, 2.319, 1.526, 0.863, 0.370, 0.106])
    Rhub = 1.5
    Rtip = 63.0
    hubheight = 80.0
    precone = 2.5
    tilt = -5.0
    yaw = 0.0
    B = 3

    # airfoils
    basepath = '/Users/Andrew/Dropbox/NREL/5MW_files/5MW_AFFiles/'

    # load all airfoils
    airfoil_types = [0]*8
    airfoil_types[0] = basepath + 'Cylinder1.dat'
    airfoil_types[1] = basepath + 'Cylinder2.dat'
    airfoil_types[2] = basepath + 'DU40_A17.dat'
    airfoil_types[3] = basepath + 'DU35_A17.dat'
    airfoil_types[4] = basepath + 'DU30_A17.dat'
    airfoil_types[5] = basepath + 'DU25_A17.dat'
    airfoil_types[6] = basepath + 'DU21_A17.dat'
    airfoil_types[7] = basepath + 'NACA64_A17.dat'

    # place at appropriate radial stations
    af_idx = [0, 0, 1, 2, 3, 3, 4, 5, 5, 6, 6, 7, 7, 7, 7, 7, 7]

    n = len(r)
    af = [0]*n
    for i in range(n):
        af[i] = airfoil_types[af_idx[i]]

    # atmosphere
    rho = 1.225
    mu = 1.81206e-5
    shearExp = 0.2
    Ubar = 6.0

    # operational conditions
    Vin = 3.0
    Vout = 25.0
    ratedPower = 5e6
    minOmega = 0.0
    maxOmega = 12.0
    tsr_opt = 7.55
    pitch_opt = 0.0


    # options
    nSectors_power_integration = 4
    tsr_sweep_step_size = 0.25
    npts_power_curve = 200
    drivetrainType = 'geared'
    AEP_loss_factor = 1.0

    # -------------------------




    # ------ OpenMDAO setup -------------------

    rotor = RotorAeroVS()

    # aero analysis
    geom = CCBladeGeometry()
    geom.Rtip = Rtip
    geom.precone = precone

    rotor.replace('geom', geom)


    analysis = CCBlade()

    analysis.r = r
    analysis.chord = chord
    analysis.theta = theta
    analysis.Rhub = Rhub
    analysis.Rtip = Rtip
    analysis.hubheight = hubheight
    analysis.airfoil_files = af
    analysis.precone = precone
    analysis.tilt = tilt
    analysis.yaw = yaw
    analysis.B = B
    analysis.rho = rho
    analysis.mu = mu
    analysis.shearExp = shearExp
    analysis.nSector = nSectors_power_integration

    rotor.replace('analysis', analysis)



    analysis2 = CCBlade()

    analysis2.r = r
    analysis2.chord = chord
    analysis2.theta = theta
    analysis2.Rhub = Rhub
    analysis2.Rtip = Rtip
    analysis2.hubheight = hubheight
    analysis2.airfoil_files = af
    analysis2.precone = precone
    analysis2.tilt = tilt
    analysis2.yaw = yaw
    analysis2.B = B
    analysis2.rho = rho
    analysis2.mu = mu
    analysis2.shearExp = shearExp
    analysis2.nSector = nSectors_power_integration

    rotor.replace('analysis2', analysis2)


    # drivetrain efficiency
    dt = CSMDrivetrain()
    dt.drivetrainType = drivetrainType

    rotor.replace('dt', dt)

    # CDF
    cdf = RayleighCDF()
    cdf.xbar = Ubar

    rotor.replace('cdf', cdf)


    rotor.rho = rho

    # operational conditions
    rotor.control.Vin = Vin
    rotor.control.Vout = Vout
    rotor.control.ratedPower = ratedPower
    rotor.control.minOmega = minOmega
    rotor.control.maxOmega = maxOmega
    rotor.control.tsr = tsr_opt
    rotor.control.pitch = pitch_opt

    # options
    rotor.tsr_sweep_step_size = tsr_sweep_step_size
    rotor.npts_power_curve = npts_power_curve
    rotor.AEP_loss_factor = AEP_loss_factor

    rotor.run()

    print rotor.AEP
    # print rotor.brent.xstar

    print rotor.rated.V
    print rotor.rated.Omega
    print rotor.rated.pitch
    print rotor.rated.T
    print rotor.rated.Q

    import matplotlib.pyplot as plt
    plt.plot(rotor.V, rotor.P/1e6)


    # plt.figure()
    # plt.plot(r, rotor.Np_rated)
    # plt.plot(r, rotor.Tp_rated)

    # plt.figure()
    # plt.plot(r, rotor.Np_extreme)
    # plt.plot(r, rotor.Tp_extreme)
    plt.show()




