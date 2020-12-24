""" implements geometry purification for the distance geometry algorithm

This is used to clean up the structure of the molecule and enforce correct
chirality, by minimizing an error function.

The error function is minimized using the conjugate gradients method:

    1. Calculate the steepest direction: dn = - grad(Err(xn))
    2. Calculate coeff Bn as Bn = min(0, Bn^PR)

        Bn^PR = dn.(dn - dn-1) / dn-1.dn-1

    3. Update the conjugate direction: sn = dn + Bn*sn-1
    4. Perform a line search to optimize An = argmin Err(xn + An*sn)
    5. Update the position: xn+1 = xn + An*sn
    6. Recalculate the gradient. If the gradient is small, quit. Otherwise,
    return to step 1.

Style convention: Functions returning callables (i.e. functions returning
functions) and callable variables are marked by trailing underscores.

See Havel, T. F.; "Distance Geometry: Theory, Algorithms, and Chemical
Applications"; Encyclopedia of Computational Chemistry (2002) for details.

The error function formulas are found on page 11 of this paper. The gradient
formulas I derived myself. On pages 12-13, the use of four-dimensional
coordinates to improve convergence is described.
"""
import logging
import numpy
import scipy.optimize
from automol.embed._dgeom import distance_matrix_from_coordinates
from automol.embed._findif import central_difference

# uncomment this line if you want the logging statements while debugging:
logging.basicConfig(format='%(message)s', level=logging.DEBUG)

X = numpy.newaxis


def volume(xmat, idxs):
    """ calculate signed tetrahedral volume for a tetrad of atoms

    for a tetrad of four atoms (1, 2, 3, 4) around a central atom, the signed
    volume formula of this tetrahedral pyramid is given by

        d12 . (d13 x d14)

    where dij = rj - ri, . is the dot product, and x is the cross product
    """
    xmat = numpy.array(xmat)
    idxs = list(idxs)
    xyzs = xmat[:, :3][idxs]
    d12 = xyzs[1] - xyzs[0]
    d13 = xyzs[2] - xyzs[0]
    d14 = xyzs[3] - xyzs[0]
    vol = numpy.dot(d12, numpy.cross(d13, d14))
    return vol


def volume_gradient(xmat, idxs):
    """ calculate the tetrahedral volume gradient for a tetrad of atoms
    """
    xmat = numpy.array(xmat)
    idxs = list(idxs)
    xyzs = xmat[:, :3][idxs]

    grad = numpy.zeros_like(xmat)
    grad[idxs[0], :3] = (numpy.cross(xyzs[1], xyzs[3]-xyzs[2]) -
                         numpy.cross(xyzs[2], xyzs[3]))
    grad[idxs[1], :3] = +numpy.cross(xyzs[2]-xyzs[0], xyzs[3]-xyzs[0])
    grad[idxs[2], :3] = -numpy.cross(xyzs[1]-xyzs[0], xyzs[3]-xyzs[0])
    grad[idxs[3], :3] = +numpy.cross(xyzs[1]-xyzs[0], xyzs[2]-xyzs[0])

    return grad


def error_function_(lmat, umat, chi_dct=None, pla_dct=None, wdist=1., wchip=1.,
                    wdim4=1., leps=0.1, ueps=0.1):
    """ the embedding error function

    :param lmat: lower-bound distance matrix
    :param umat: upper-bound distance matrix
    :param chi_dct: chirality constraints; the keys are tuples of four atoms,
        the values are lower and upper bounds on the four-point signed volume
        of these atoms
    :param pla_dct: planarity constraints; the keys are tuples of four atoms,
        the values are lower and upper bounds on the four-point signed volume
        of these atoms
    :param wdist: weight on the distance constraint
    :param wchip: weight on the chirality/planarity constraint
    :param wdim4: weight on the fourth dimension constraint
    :param leps: denominator epsilon for lower bound distances
    :param ueps: denominator epsilon for upper bound distances
    """
    triu = numpy.triu_indices_from(lmat)
    chi_dct = {} if chi_dct is None else chi_dct
    pla_dct = {} if pla_dct is None else pla_dct
    chip_dct = {**chi_dct, **pla_dct}

    def _function(xmat):
        dmat = distance_matrix_from_coordinates(xmat)

        # distance error (equation 61 in the paper referenced above)
        ltf = ((lmat**2-dmat**2) / (leps**2+dmat**2))[triu]
        utf = ((dmat**2-umat**2) / (ueps**2+umat**2))[triu]
        ltf *= (ltf > 0.)
        utf *= (utf > 0.)
        dist_err = wdist * (numpy.vdot(utf, utf) + numpy.vdot(ltf, ltf))

        # chirality/planarity error (equation 62 in the paper referenced above)
        if chip_dct:
            vols = numpy.array(
                [volume(xmat, idxs) for idxs in chip_dct.keys()])
            lvols, uvols = map(numpy.array, zip(*chip_dct.values()))
            ltv = (lvols - vols) * (vols < lvols)
            utv = (vols - uvols) * (vols > uvols)
            chip_err = wchip * (numpy.vdot(ltv, ltv) + numpy.vdot(utv, utv))
        else:
            chip_err = 0.

        # fourth-dimension error
        if numpy.shape(xmat)[1] == 4:
            dim4_err = wdim4 * numpy.vdot(xmat[:, 3], xmat[:, 3])
        else:
            dim4_err = 0.

        return dist_err + chip_err + dim4_err

    return _function


def error_function_gradient_(lmat, umat, chi_dct=None, pla_dct=None,
                             wdist=1., wchip=1., wdim4=1., leps=0.1, ueps=0.1):
    """ the embedding error function gradient

    :param lmat: lower-bound distance matrix
    :param umat: upper-bound distance matrix
    :param chi_dct: chirality constraints; the keys are tuples of four atoms,
        the values are lower and upper bounds on the four-point signed volume
        of these atoms
    :param pla_dct: planarity constraints; the keys are tuples of four atoms,
        the values are lower and upper bounds on the four-point signed volume
        of these atoms
    :param wdist: weight on the distance constraint
    :param wchip: weight on the chirality/planarity constraint
    :param wdim4: weight on the fourth dimension constraint
    :param leps: denominator epsilon for lower bound distances
    :param ueps: denominator epsilon for upper bound distances
    """
    chi_dct = {} if chi_dct is None else chi_dct
    pla_dct = {} if pla_dct is None else pla_dct
    chip_dct = {**chi_dct, **pla_dct}

    def _gradient(xmat):
        dmat = distance_matrix_from_coordinates(xmat)

        # distance error gradient
        utf = (dmat**2-umat**2) / (ueps**2+umat**2)
        ltf = (lmat**2-dmat**2) / (leps**2+dmat**2)
        utg = (+4.*utf/(ueps**2+umat**2))*(utf > 0.)
        ltg = (-4.*ltf/(leps**2+dmat**2)**2)*(leps**2+lmat**2)*(ltf > 0.)
        utg = utg[:, :, X]
        ltg = ltg[:, :, X]
        xmx = xmat[:, X, :] - xmat[X, :, :]
        dist_grad = numpy.sum(xmx*(ltg + utg), axis=1)
        dist_grad *= wdist

        # chirality/planarity error gradient
        if chip_dct:
            vols = numpy.array(
                [volume(xmat, idxs) for idxs in chip_dct.keys()])
            vol_grads = numpy.array(
                [volume_gradient(xmat, idxs) for idxs in chip_dct.keys()])
            lvols, uvols = map(numpy.array, zip(*chip_dct.values()))
            ltv = (lvols - vols) * (vols < lvols)
            utv = (vols - uvols) * (vols > uvols)
            ltg = -2. * ltv[:, X, X] * vol_grads
            utg = +2. * utv[:, X, X] * vol_grads
            chip_grad = numpy.sum(ltg+utg, axis=0)
            chip_grad *= wchip
        else:
            chip_grad = numpy.zeros_like(xmat)

        # fourth-dimension error gradient
        if numpy.shape(xmat)[1] == 4:
            dim3_zeros = numpy.zeros_like(xmat[:, :3])
            dim4_grad = numpy.hstack([dim3_zeros, 2*xmat[:, 3:]])
            dim4_grad *= wdim4
        else:
            dim4_grad = numpy.zeros_like(xmat)

        return dist_grad + chip_grad + dim4_grad

    return _gradient


def error_function_numerical_gradient_(lmat, umat, chi_dct=None, pla_dct=None,
                                       wdist=1., wchip=1., wdim4=1.,
                                       leps=0.1, ueps=0.1):
    """ the gradient of the distance error function

    (For testing purposes only; Used to check the analytic gradient formula.)
    """

    erf_ = error_function_(lmat, umat, chi_dct=chi_dct, pla_dct=pla_dct,
                           wdist=wdist, wchip=wchip, wdim4=wdim4,
                           leps=leps, ueps=ueps)

    def _gradient(xmat):
        grad = central_difference(erf_, xmat, npts=11)
        return grad

    return _gradient


def polak_ribiere_beta(sd1, sd0):
    """ calculate the Polak-Ribiere Beta coefficient
    """
    return numpy.vdot(sd1, sd1-sd0) / numpy.vdot(sd0, sd0)


def line_search_alpha(err_, sd1, cd1):
    """ perform a line search to determine the alpha coefficient
    """

    # define the objective function
    def _function_of_alpha(alpha):
        return err_(sd1 + alpha*cd1)

    # do the line search and make sure it worked
    res = scipy.optimize.minimize_scalar(_function_of_alpha)
    assert res.success, ("Line search for alpha failed!\n", str(res))

    # get the result
    alpha = res.x

    return alpha


def cleaned_up_coordinates(xmat, lmat, umat, chi_dct=None, pla_dct=None,
                           conv_=None, thresh=1e-1, maxiter=None,
                           chi_flip=True):
    """ clean up coordinates by conjugate-gradients error minimization

    :param xmat: the initial guess coordinates to be cleaned up
    :param lmat: lower-bound distance matrix
    :param umat: upper-bound distance matrix
    :param chi_dct: chirality constraints; the keys are tuples of four atoms,
        the values are lower and upper bounds on the four-point signed volume
        of these atoms
    :param pla_dct: planarity constraints; the keys are tuples of four atoms,
        the values are lower and upper bounds on the four-point signed volume
        of these atoms
    :param conv_: a callable convergence checker function of xmat, err, and
        grad which returns True if the geometry is converged
    :param thresh: convergence threshold, specifying the maximum gradient
        value, if the default convergence checker is being used
    :param maxiter: maximum number of iterations; default is three times the
        number of coordinates
    :chi_flip: whether or not to invert the structure if more than half of the
        chiralities are reversed
    """
    xmat = numpy.array(xmat)

    # If less than half of the chiralities have correct sign, invert the
    # geometry
    if chi_flip and chi_dct:
        current_vols = numpy.array(
            [volume(xmat, idxs) for idxs in chi_dct.keys()])
        target_vols = numpy.array(list(map(numpy.average, chi_dct.values())))
        comparison = numpy.sign(current_vols) == numpy.sign(target_vols)
        fraction = numpy.average(comparison)
        if fraction < 0.5:
            xmat *= -1.

    maxiter = int(numpy.size(xmat) * 3 if maxiter is None else maxiter)

    err_ = error_function_(
        lmat, umat, chi_dct=chi_dct, pla_dct=pla_dct, wdim4=1.)
    grad_ = error_function_gradient_(
        lmat, umat, chi_dct=chi_dct, pla_dct=pla_dct, wdim4=1.)
    conv_ = (quantitative_convergence_checker_(thresh) if conv_ is None
             else conv_)

    xmat, conv = minimize_error(xmat, err_, grad_, conv_, maxiter)
    return xmat, conv


def quantitative_convergence_checker_(thresh=1e-1):
    """ tight, quantitative convergence checker
    """

    def _is_converged(xmat, err, grad):
        assert numpy.shape(xmat) == numpy.shape(grad)
        grad_max = numpy.amax(numpy.abs(grad))
        logging.info('\tError: {:f}'.format(err))
        logging.info('\tMax gradient: {:f}'.format(grad_max))
        logging.info('\n')
        return grad_max < thresh

    return _is_converged


def minimize_error(xmat, err_, grad_, conv_, maxiter=None):
    """ do conjugate-gradients error minimization

    :param err_: a callable error function of xmat
    :param grad_: a callable error gradient function of xmat
    :param conv_: a callable convergence checker function of xmat, err_(xmat),
        and grad_(xmat) which returns True if the geometry is converged

    :returns: the optimized coordinates and a boolean which is True if
        converged and False if not
    """
    maxiter = numpy.size(xmat) * 3 if maxiter is None else maxiter

    sd0 = None
    cd0 = None
    logging.info('Initial error: {:f}'.format(err_(xmat)))

    converged = False

    for niter in range(maxiter):
        logging.info('Iteration {:d}'.format(niter))

        # 1. Calculate the steepest direction
        sd1 = -grad_(xmat)

        # 2-3. Determine the conjugate direction
        if sd0 is None:
            cd1 = sd1
        else:
            # 2. Cumpute beta
            beta = min(0., polak_ribiere_beta(sd1, sd0))

            # 3. determine step direction
            cd1 = sd1 + beta * cd0

        # 4. Perform a line search
        alpha = line_search_alpha(err_, xmat, cd1)

        # 5. Check convergence
        if conv_(xmat, err_(xmat), sd1):
            converged = True
            break

        # 6. Take the step
        xmat += alpha*cd1

        sd0 = sd1
        cd0 = cd1

    logging.info('Niter: {:d}'.format(niter))
    logging.info('Converged: {:s}'.format('Yes' if converged else 'No'))
    logging.info('\n')

    return xmat, converged
