import numpy as np
import scipy as sp
import scipy.optimize as optimize
import itertools
from pydantic.dataclasses import dataclass

from FisInMa.model import FisherModel, FisherModelParametrized, VariableDefinition
from FisInMa.solving import calculate_fisher_criterion, fisher_determinant


def _create_comparison_matrix(n, value=1.0):
    """Creates a matrix for linear constraints of scipy such that lower and higher values can be compared

    Args:
        n (int): Dimensionality of the resulting matrix will be (n-1,n)
        value (float, optional): Values of the matrix' entries.

    Returns:
        np.ndarary: Matrix of dimension (n-1,n) with entries at A[i][i] (positive) and A[i][i+1] (negative).
    """
    
    # Fill the matrix like so:
    #         | 1 -1  0  0 ... |
    # A = | 0  1 -1  0 ... |
    #     | 0  0  1 -1 ... |
    #     | ...            |
    #     This enables us to compare variables like to
    #     a_(i) - a_(i+1) <= - min_distance
    # <=> a_(i) + min_distance <= a_(i+1)
    A = np.zeros((max(0,n-1), max(0,n)))
    for i in range(n-1):
        A[i][i] = value
        A[i][i+1] = -value
    return A


class PenaltyConfig:
    arbitrary_types_allowed = True


@dataclass(config=PenaltyConfig)
class PenaltyInformation:
    penalty: float
    penalty_ode_t0: float
    # TODO - add penalty for ode_x0 when sampling is done
    # penalty_ode_x0: List[List[float]]
    penalty_inputs: float
    penalty_times: float
    penalty_summary: dict


def penalty_structure_zigzag(v, dv):
    """Define the zigzag structure of the penalty potential between two allowed discrete values. 
    Used in function :py:meth:`discrete_penalty_individual_template`.

    :param v: The distance between the optimized value and the smaller neighboring discrete value.
    :type v: float
    :param dv: The distance between smaller and larger neighboring discrete values.
    :type dv: float

    :return: The value of the penalty potential.
    :rtype: float
    """
    return np.abs(1 - 2 * v / dv)


def penalty_structure_cos(v, dv):
    """Define the cosine structure of the penalty potential between two allowed discrete values. 
    Used in function :py:meth:`discrete_penalty_individual_template`.

    :param v: The distance between the optimized value and the smaller neighboring discrete value.
    :type v: float
    :param dv: The distance between smaller and larger neighboring discrete values.
    :type dv: float

    :return: The value of the penalty potential.
    :rtype: float
    """
    return 0.5 * (1 + np.cos(2*np.pi * v / dv))


def penalty_structure_gauss(v, dv):
    """Define the two-Gaussian-functions structure of the penalty potential between two allowed discrete values. 
    Used in function :py:meth:`discrete_penalty_individual_template`.

    :param v: The distance between the optimized value and the smaller neighboring discrete value.
    :type v: float
    :param dv: The distance between smaller and larger neighboring discrete values.
    :type dv: float

    :return: The value of the penalty potential.
    :rtype: float
    """
    sigma = dv / 10
    return np.exp(- 0.5 * v**2 / sigma**2) +  np.exp(- 0.5 * (v - dv)**2 / sigma**2)


def discrete_penalty_individual_template(vals, vals_discr, pen_structure):
    r"""The discretization penalty function template.
    If there is no penalty, a function gives 1 and 0 in case of the maximum penalty for data points that do not sit on the desired discretization points.

    The resulting contribution of the penalty function is calculated as a product of all penalty values  for each value :math:`v`.
    
    .. math::

      U = \prod_{i=1} U_1(v_i).


    :param vals: The array of values to optimize :math:`v`.
    :type vals: np.ndarary
    :param vals_discr: The array of allowed discrete values :math:`v^{\text{discr}}`.
    :type vals_discr: np.ndarary
    :param pen_structure: Define the structure of the template.

        - penalty_structure_zigzag
            ...
        - penalty_structure_cos
            ...
        - penalty_structure_gauss
            ...

    .. figure:: discretization_template.png
      :align: center
      :width: 450

      The discretization penalty function for discrete values :math:`v^{\text{discr}} = [1, 2, 3, 6, 8, 9]` for different penalty structures.

    :type pen_structure: Callable
    
    :return: The array of the penalty potential values for *vals*. The resulting contribution (product) of the penalty function.
    :rtype: np.ndarary, float
    """
    prod = []
    for v in vals:
        for i in range (len(vals_discr)-1):
            if vals_discr[i] <= v <= vals_discr[i+1]:
                dx = vals_discr[i+1] - vals_discr[i]
                prod.append(pen_structure(v - vals_discr[i], dx))
    pen = np.product(prod)
    return pen, prod


def discrete_penalty_calculator_default(vals, vals_discr):
    r"""The discretization penalty function taken as a product of all differences between the optimized value :math:`v` and all possible discrete values allowed :math:`v^{\text{discr}}`.
    If there is no penalty, a function gives 1 and 0 in case of the maximum penalty for data points that do not sit on the desired discretization points.
    
    .. math::

      U_1(v) = 1 - \sqrt[N]{\prod_{k=1}^N (v - v^{\text{discr}}_{k})} \frac{1}{\max(v^{\text{discr}}) - \min(v^{\text{discr}})},

    where :math:`N` is the size of the vector of the allowed discrete values :math:`v^{\text{discr}}`. 
    The resulting contribution of the penalty function is a product of the potential values for each value :math:`v`.
    
    .. figure:: discretization_product.png
      :align: center
      :width: 400

      The discretization penalty function for discrete values :math:`v^{\text{discr}} = [1, 2, 3, 6, 8, 9]`.

    The resulting contribution of the penalty function is calculated as a product of all penalty values for each value :math:`v`.
    
    .. math::

      U = \prod_{i=1} U_1(v_i).


    :param vals: The array of values to optimize :math:`v`.
    :type vals: np.ndarary
    :param vals_discr: The array of allowed discrete values :math:`v^{\text{discr}}`.
    :type vals_discr: np.ndarary

    :return: The array of the penalty potential values for *vals*. The resulting contribution (product) of the penalty function.
    :rtype: np.ndarary, float
    """
    # TODO - document this function
    # TODO - should be specifiable as parameter in optimization routine
    # Calculate the penalty for provided values
    prod = np.array([1 - (np.abs(np.prod((vals_discr - v))))**(1.0 / len(vals_discr)) / (np.max(vals_discr) - np.min(vals_discr)) for v in vals])
    pen = np.product(prod)
    # Return the penalty and the output per inserted variable
    return pen, prod


DISCRETE_PENALTY_FUNCTIONS = {
    "default": discrete_penalty_calculator_default,
    "product_difference": discrete_penalty_calculator_default,
    "individual_zigzag": lambda vals, vals_discr: discrete_penalty_individual_template(vals, vals_discr, penalty_structure_zigzag),
    "individual_cos": lambda vals, vals_discr: discrete_penalty_individual_template(vals, vals_discr, penalty_structure_cos),
    "individual_gauss": lambda vals, vals_discr: discrete_penalty_individual_template(vals, vals_discr, penalty_structure_gauss),
}


def _discrete_penalizer(fsmp, penalizer_name="default"):
    penalizer = DISCRETE_PENALTY_FUNCTIONS[penalizer_name]
    # Penalty contribution from initial times
    pen_ode_t0 = 1
    pen_ode_t0_full = []
    if type(fsmp.ode_t0_def) is VariableDefinition:
        # Now we can expect that this parameter was sampled
        # thus we want to look for possible discretization values
        discr = fsmp.ode_t0_def.discrete
        if type(discr) is np.ndarray:
            values = fsmp.ode_t0
            pen_ode_t0, pen_ode_t0_full = penalizer(values, discr)

    # Penalty contribution from inputs
    pen_inputs = 1
    pen_inputs_full = []
    for var_def, var_val in zip(fsmp.inputs_def, fsmp.inputs):
        if type(var_def) == VariableDefinition:
            discr = var_def.discrete
            if type(discr) is np.ndarray:
                values = var_val
                p, p_full = penalizer(values, discr)
                pen_inputs *= p
                pen_inputs_full.append(p_full)

    # Penalty contribution from times
    pen_times = 1
    pen_times_full = []
    if type(fsmp.times_def) is VariableDefinition:
        discr = fsmp.times_def.discrete
        if type(discr) is np.ndarray:
            if fsmp.identical_times==True:
                values = fsmp.times
                pen_times, pen_times_full = penalizer(values, discr)
            else:
                pen_times_full = []
                for index in itertools.product(*[range(len(q)) for q in fsmp.inputs]):
                    if fsmp.identical_times==True:
                        values = fsmp.times
                    else:
                        values = fsmp.times[index]
                    p, p_full = penalizer(values, discr)
                    pen_times *= p
                    pen_times_full.append(p_full)

    # Calculate the total penalty
    pen = pen_ode_t0 * pen_inputs * pen_times

    # Create a summary
    pen_summary = {
        "ode_t0": pen_ode_t0_full,
        "inputs": pen_inputs_full,
        "times": pen_times_full
    }

    # Store values in class
    ret = PenaltyInformation(
        penalty=pen,
        penalty_ode_t0=pen_ode_t0,
        penalty_inputs=pen_inputs,
        penalty_times=pen_times,
        penalty_summary=pen_summary,
    )

    # Store all results and calculate total penalty
    return pen, ret


def __scipy_optimizer_function(X, fsmp: FisherModelParametrized, full=False, discrete_penalizer="default", kwargs_dict={}):
    total = 0
    # Get values for ode_t0
    if fsmp.ode_t0_def is not None:
        fsmp.ode_t0 = X[:fsmp.ode_t0_def.n]
        total += fsmp.ode_t0_def.n
    
    # Get values for ode_x0
    if fsmp.ode_x0_def is not None:
        fsmp.ode_x0 = X[total:total + fsmp.ode_x0_def.n * fsmp.ode_x0.size]
        total += fsmp.ode_x0_def.n

    # Get values for times
    if fsmp.times_def is not None:
        fsmp.times = np.sort(X[total:total+fsmp.times.size].reshape(fsmp.times.shape), axis=-1)
        total += fsmp.times.size

    # Get values for inputs
    for i, inp_def in enumerate(fsmp.inputs_def):
        if inp_def is not None:
            fsmp.inputs[i]=X[total:total+inp_def.n]
            total += inp_def.n

    # Calculate the correct criterion
    fsr = calculate_fisher_criterion(fsmp, **kwargs_dict)

    # Calculate the discretization penalty
    penalty, penalty_summary = _discrete_penalizer(fsmp, discrete_penalizer)
    
    # Include information about the penalty
    fsr.penalty_discrete_summary = penalty_summary

    # Return full result if desired
    if full:
        return fsr
    return -fsr.criterion * penalty


def _scipy_calculate_bounds_constraints(fsmp: FisherModelParametrized):
    # Define array for upper and lower bounds
    ub = []
    lb = []
    
    # Define constraints via equation lc <= B.dot(x) uc
    # lower and upper constraints lc, uc and matrix B
    lc = []
    uc = []

    # Determine the number of mutable variables which can be sampled over
    n_times = np.product(fsmp.times.shape) if fsmp.times_def  is not None else 0
    n_inputs = [len(q) if q_def is not None else 0 for q, q_def in zip(fsmp.inputs, fsmp.inputs_def)]
    n_mut = [
        fsmp.ode_t0_def.n if fsmp.ode_t0_def is not None else 0,
        fsmp.ode_x0_def.n if fsmp.ode_x0_def is not None else 0,
        n_times,
        *n_inputs
    ]
    B = np.eye(0)

    # Go through all possibly mutable variables and gather information about constraints and bounds
    # Check if initial times are sampled over
    if type(fsmp.ode_t0_def)==VariableDefinition:
        # Bounds for value
        lb += [fsmp.ode_t0_def.lb] * fsmp.ode_t0_def.n
        ub += [fsmp.ode_t0_def.ub] * fsmp.ode_t0_def.n
        
        # Constraints on variables
        lc += [-np.inf] * (fsmp.ode_t0_def.n-1)
        uc += [fsmp.ode_t0_def.min_distance if fsmp.ode_t0_def.min_distance is not None else np.inf] * (fsmp.ode_t0_def.n-1)
        
        # Define matrix A which will extend B
        A = _create_comparison_matrix(fsmp.ode_t0_def.n)
        B = np.block([[B,np.zeros((B.shape[0],A.shape[1]))],[np.zeros((A.shape[0],B.shape[1])),A]])

    # Check if initial values are sampled over
    if type(fsmp.ode_x0_def)==VariableDefinition:
        # Bounds for value
        lb.append(fsmp.ode_x0_def.lb)
        ub.append(fsmp.ode_x0_def.ub)
        
        # Constraints on variables
        lc += []
        uc += []

        # Extend matrix B
        A = np.eye(0)
        B = np.block([[B,np.zeros((B.shape[0],A.shape[1]))],[np.zeros((A.shape[0],B.shape[1])),A]])

    # Check if times are sampled over
    if type(fsmp.times_def)==VariableDefinition:
        # How many time points are we sampling?
        n_times = np.product(fsmp.times.shape)

        # Store lower and upper bound
        lb += [fsmp.times_def.lb] * n_times
        ub += [fsmp.times_def.ub] * n_times

        # Constraints on variables
        lc += [-np.inf] * (n_times-1)
        uc += [-fsmp.times_def.min_distance if fsmp.times_def.min_distance is not None else 0.0] * (n_times-1)

        # Extend matrix B
        A = _create_comparison_matrix(n_times)
        B = np.block([[B,np.zeros((B.shape[0],A.shape[1]))],[np.zeros((A.shape[0],B.shape[1])),A]])
    
    # Check which inputs are sampled
    for inp_def in fsmp.inputs_def:
        if type(inp_def)==VariableDefinition:
            # Store lower and upper bound
            lb += [inp_def.lb] * inp_def.n
            ub += [inp_def.ub] * inp_def.n

            # Constraints on variables
            lc += [-np.inf] * (inp_def.n-1)
            uc += [-inp_def.min_distance if inp_def.min_distance is not None else 0.0] * (inp_def.n-1)

            # Create correct matrix matrix to store
            A = _create_comparison_matrix(inp_def.n)
            B = np.block([[B,np.zeros((B.shape[0],A.shape[1]))],[np.zeros((A.shape[0],B.shape[1])),A]])

    bounds = list(zip(lb, ub))
    constraints = optimize.LinearConstraint(B, lc, uc)
    return bounds, constraints


def __initial_guess(fsmp: FisherModelParametrized):
    x0 = np.concatenate([
        np.array(fsmp.ode_x0).flatten() if fsmp.ode_x0_def is not None else [],
        np.array(fsmp.ode_t0).flatten() if fsmp.ode_t0_def is not None else [],
        np.array(fsmp.times).flatten() if fsmp.times_def is not None else [],
        *[
            np.array(inp_mut_val).flatten() if inp_mut_val is not None else []
            for inp_mut_val in fsmp.inputs_mut
        ]
    ])
    return x0


def __update_arguments(optim_func, optim_args, kwargs):
    # Gather all arguments which can be supplied to the optimization function and check for intersections
    o_keys = set(optim_func.__code__.co_varnames)

    # Take all keys which are ment to go into the routine and put it in the corresponding dictionary
    intersect = {key: kwargs.pop(key) for key in o_keys & kwargs.keys()}

    # Update the arguments for the optimization routine. Pass everything else to our custom methods.
    optim_args.update(intersect)

    return optim_args, kwargs


def __scipy_differential_evolution(fsmp: FisherModelParametrized, discrete_penalizer="default", **kwargs):
    # Create bounds, constraints and initial guess
    bounds, constraints = _scipy_calculate_bounds_constraints(fsmp)
    x0 = __initial_guess(fsmp)

    opt_args = {
        "func": __scipy_optimizer_function,
        "bounds": bounds,
        "args":(fsmp, False, discrete_penalizer, kwargs),
        "disp": True,
        "polish": True,
        "updating": 'deferred',
        "workers": -1,
        #"constraints":constraints,
        "x0": x0
    }

    # Check for intersecting arguments and update the default arguments in opt_args with arguments from kwargs.
    opt_args, kwargs = __update_arguments(optimize.differential_evolution, opt_args, kwargs)

    # Actually call the optimization function
    res = optimize.differential_evolution(**opt_args)

    # Return the full result
    return __scipy_optimizer_function(res.x, fsmp, full=True, discrete_penalizer=discrete_penalizer, kwargs_dict=kwargs)


def __scipy_brute(fsmp: FisherModelParametrized, discrete_penalizer="default", **kwargs):
    # Create bounds and constraints
    bounds, constraints = _scipy_calculate_bounds_constraints(fsmp)

    opt_args = {
        "func": __scipy_optimizer_function,
        "ranges": bounds,
        "args":(fsmp, False, discrete_penalizer, kwargs),
        "Ns":3,
        "full_output":0,
        "finish": None,
        "disp":True,
        "workers":-1
    }

    # Check for intersecting arguments and update the default arguments in opt_args with arguments from kwargs.
    opt_args, kwargs = __update_arguments(optimize.brute, opt_args, kwargs)

    # Actually call the optimization function
    res = optimize.brute(**opt_args)

    return __scipy_optimizer_function(res, fsmp, full=True, discrete_penalizer=discrete_penalizer, kwargs_dict=kwargs)


def __scipy_basinhopping(fsmp: FisherModelParametrized, discrete_penalizer="default", **kwargs):
    # Create bounds, constraints and initial guess
    bounds, constraints = _scipy_calculate_bounds_constraints(fsmp)
    x0 = __initial_guess(fsmp)

    opt_args = {
        "func": __scipy_optimizer_function,
        "x0": x0,
        "minimizer_kwargs":{"args":(fsmp, False, discrete_penalizer, kwargs), "bounds": bounds},
        "disp":True,
    }

    # Check for intersecting arguments and update the default arguments in opt_args with arguments from kwargs.
    opt_args, kwargs = __update_arguments(optimize.basinhopping, opt_args, kwargs)

    # Actually call the optimization function
    res = optimize.basinhopping(**opt_args)

    return __scipy_optimizer_function(res.x, fsmp, full=True, discrete_penalizer=discrete_penalizer, kwargs_dict=kwargs)
