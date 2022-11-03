import unittest
import numpy as np
import copy
import scipy as sp
import time

from FisInMa.model import FisherModel, FisherModelParametrized
from FisInMa.solving import *

from test.setUp import Setup_Class

# Define a RHS of ODE where exact result is known
def ode_fun(t, x, inputs, parameters, ode_args):
    (A, B) = x
    (T,) = inputs
    (a, b) = parameters
    return [
        a - b*T*A,
        b - a*T*B
    ]

def ode_dfdx(t, x, inputs, parameters, ode_args):
    (A, B) = x
    (T,) = inputs
    (a, b) = parameters
    return [
        [- b*T, 0],
        [0, - a*T]
    ]

def ode_dfdp(t, x, inputs, parameters, ode_args):
    (A, B) = x
    (T,) = inputs
    (a, b) = parameters
    return [
        [1, - T*A],
        [- T*B, 1]
    ]

def g(t, x, inputs, parameters, ode_args):
    (A, B) = x
    return A**2

def dgdx(t, x, inputs, parameters, ode_args):
    (A, B) = x
    return [
        [2*A, 0]
    ]

def dgdp(t, x, inputs, parameters, ode_args):
    return [
        [0 ,0, 0],
        [0 ,0, 0]
    ]

def g_exact(t, x0, inputs, parameters, ode_args):
    (T,) = inputs
    (a, b) = parameters
    int_constant = [
        x0[0] - a/(b*T),
        x0[1] - b/(a*T)
    ]
    return [
        a/(b*T) + int_constant[0] * np.exp(-b*T*t),
        b/(a*T) + int_constant[1] * np.exp(-a*T*t)
    ]

def dgdp_exact(t, x0, inputs, parameters, ode_args):
    (T,) = inputs
    (a, b) = parameters
    int_constant = [
        x0[0] - a/(b*T),
        x0[1] - b/(a*T)
    ]
    return [
        [(1 - np.exp(-b*T*t))/(b*T), a/(b**2*T)*(-1+np.exp(-b*T*t)+b*T*t*np.exp(-b*T*t))-x0[0]*t*T*np.exp(-b*T*t)],
        [b/(a**2*T)*(-1+np.exp(-a*T*t)+a*T*t*np.exp(-a*T*t))-x0[1]*t*T*np.exp(-a*T*t), (1 - np.exp(-a*T*t))/(a*T)]
    ]


class Setup_Convergence(unittest.TestCase):
    @classmethod
    def setUp(self, n_times=4, n_inputs=3, identical_times=False):
        self.x0=[1.0, 0.5]
        self.t0=0.0
        self.times=np.linspace(0.0, 10.0, n_times)
        self.n_times = n_times
        self.n_inputs = n_inputs
        self.inputs=[
            np.linspace(0.8, 1.2, n_inputs)
        ]
        
        self.parameters=(0.2388, 0.74234)
        # n_ode_args = 3
        self.ode_args=None
        self.fsm = FisherModel(
            ode_fun=ode_fun,
            ode_dfdx=ode_dfdx,
            ode_dfdp=ode_dfdp,
            ode_x0=self.x0,
            ode_t0=self.t0,
            times=self.times,
            inputs=self.inputs,
            parameters=self.parameters,
            ode_args=self.ode_args,
            obs_fun=g,
            obs_dfdx=dgdx,
            obs_dfdp=dgdp,
            identical_times=identical_times,
        )
        self.fsmp = FisherModelParametrized.init_from(self.fsm)


class TestConvergence(Setup_Convergence):
    def test_ode_rhs_exact_solution(self):
        # Obtain the Sensitivity Matrix from our method
        fsmp = copy.deepcopy(self.fsmp)
        S, C, solutions = get_S_matrix(fsmp)
        # Manually create the Fisher matrix as it should be with exact result of ODE

        # Calculate observables of exact solution for all entries
        n_x0 = len(fsmp.ode_x0[0])
        n_o = len(fsmp.ode_x0[0])
        n_p = len(fsmp.parameters)
        n_inputs = self.n_inputs

        # The shape of the initial S matrix is given by
        S_own = np.zeros((n_p, n_o, n_inputs, self.n_times))
        
        # Test that the ODE is solved correctly
        for sol in solutions:# , sol_ode_own, sol_sens_own in zip(solutions, solutions_ode_exact_own, solutions_sens_exact_own):
            sol_ode_calc = sol.ode_solution.y[:n_x0].T
            sol_sens_calc = sol.ode_solution.y[n_x0:].T

            sol_ode_own = np.array([g_exact(t, sol.ode_x0, sol.inputs, sol.parameters, sol.ode_args) for t in sol.times])
            sol_sens_own = np.array([dgdp_exact(t, sol.ode_x0, sol.inputs, sol.parameters, sol.ode_args) for t in sol.times])

            s = np.swapaxes(sol_sens_own.reshape((len(sol.times), n_o, n_p)), 0, 2)
            i = np.where(fsmp.inputs[0] == sol.inputs)
            S_own[(slice(None), slice(None), i[0][0], slice(None))] = s

            np.testing.assert_almost_equal(sol_ode_calc, sol_ode_own, decimal=3)
            np.testing.assert_almost_equal(sol_sens_calc, sol_sens_own.reshape((len(sol.times), -1)), decimal=3)
        # Test that the resulting sensitivities are the same
        S_own = S_own.reshape((n_p, -1))
        F_own = np.matmul(S_own, S_own.T)
        F = np.matmul(S,S.T)
        np.testing.assert_almost_equal(S_own, S, decimal=3)
        np.testing.assert_almost_equal(F_own, F, decimal=2)
