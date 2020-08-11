""" molecular graph reaction identifiers

Function arguments:
    Each function takes a list of reactant graphs and a list of product graphs.
    Note that the reactant graphs *cannot* have overlapping atom keys, and
    likewise for the product graphs. Otherwise, there would be no way to
    express the bonds broken and formed between reactants.

Function return values:
    Each function returns a list of "transformations" (see graph.trans)
    describing bonds broken and formed to transform reactants into products,
    along with sort indices for putting the reactants and products in a
    standard sort order for each reaction.
"""
import itertools
from automol import formula
import automol.graph.trans as trans
import automol.convert.graph as graph_convert
from automol.graph._graph_base import string
from automol.graph._graph import atom_count
from automol.graph._graph import heavy_atom_count
from automol.graph._graph import electron_count
from automol.graph._graph import atom_keys
from automol.graph._graph import bond_keys
from automol.graph._graph import explicit
from automol.graph._graph import without_stereo_parities
from automol.graph._graph import union
from automol.graph._graph import union_from_sequence
from automol.graph._graph import connected_components
from automol.graph._graph import full_isomorphism
from automol.graph._graph import add_bonds
from automol.graph._graph import remove_bonds
from automol.graph._graph import add_atom_explicit_hydrogen_keys
from automol.graph._graph import unsaturated_atom_keys


def hydrogen_migration(rct_gras, prd_gras):
    """ find a hydrogen migration transformation

    Hydrogen migrations are identified by adding a hydrogen to an unsaturated
    site of the reactant and adding a hydrogen to an unsaturated site of the
    product and seeing if they match up. If so, we have a hydrogen migration
    between these two sites.
    """
    _assert_is_valid_reagent_graph_list(rct_gras)
    _assert_is_valid_reagent_graph_list(prd_gras)

    tras = []
    rct_idxs = None
    prd_idxs = None

    if len(rct_gras) == 1 and len(prd_gras) == 1:
        gra1, = rct_gras
        gra2, = prd_gras
        print('gras')
        print(gra1)
        print(gra2)
        h_atm_key1 = max(atom_keys(gra1)) + 1
        h_atm_key2 = max(atom_keys(gra2)) + 1

        atm_keys1 = unsaturated_atom_keys(gra1)
        atm_keys2 = unsaturated_atom_keys(gra2)
        print('keys')
        for atm_key1, atm_key2 in itertools.product(atm_keys1, atm_keys2):
            print(atm_key1, atm_key2)
            gra1_h = add_atom_explicit_hydrogen_keys(
                gra1, {atm_key1: [h_atm_key1]})
            gra2_h = add_atom_explicit_hydrogen_keys(
                gra2, {atm_key2: [h_atm_key2]})

            inv_atm_key_dct = full_isomorphism(gra2_h, gra1_h)
            if inv_atm_key_dct:
                tra = trans.from_data(
                    frm_bnd_keys=[{atm_key1,
                                   inv_atm_key_dct[h_atm_key2]}],
                    brk_bnd_keys=[{inv_atm_key_dct[atm_key2],
                                   inv_atm_key_dct[h_atm_key2]}])
                tras.append(tra)

                rct_idxs = (0,)
                prd_idxs = (0,)

    tras = tuple(tras)

    return tras, rct_idxs, prd_idxs


def hydrogen_abstraction(rct_gras, prd_gras):
    """ find a hydrogen abstraction transformation

    Hydrogen abstractions are identified first by checking whether the
    molecular formulas are consistent with a reaction of the form R1H + R2 =>
    R2H + R1. If they do, we identify the abstraction sites by adding hydrogens
    to unsaturated sites of the R1 product to see if we get the R1H reactant.
    We then do the same for the R2 reactant and the R2H product.
    """
    _assert_is_valid_reagent_graph_list(rct_gras)
    _assert_is_valid_reagent_graph_list(prd_gras)

    tras = []
    rct_idxs = None
    prd_idxs = None

    if len(rct_gras) == 2 and len(prd_gras) == 2:
        rct_fmls = list(map(graph_convert.formula, rct_gras))
        prd_fmls = list(map(graph_convert.formula, prd_gras))

        ret = formula.reac.argsort_hydrogen_abstraction(rct_fmls, prd_fmls)
        if ret:
            rct_idxs_, prd_idxs_ = ret

            q1h_gra, q2_gra = list(map(rct_gras.__getitem__, rct_idxs_))
            q2h_gra, q1_gra = list(map(prd_gras.__getitem__, prd_idxs_))

            rets1 = _partial_hydrogen_abstraction(q1h_gra, q1_gra)
            rets2 = _partial_hydrogen_abstraction(q2h_gra, q2_gra)
            for ret1, ret2 in itertools.product(rets1, rets2):
                q1h_q_atm_key, q1h_h_atm_key, _ = ret1
                _, _, q2_q_atm_key = ret2

                frm_bnd_key = frozenset({q2_q_atm_key, q1h_h_atm_key})
                brk_bnd_key = frozenset({q1h_q_atm_key, q1h_h_atm_key})

                tra = trans.from_data(frm_bnd_keys=[frm_bnd_key],
                                      brk_bnd_keys=[brk_bnd_key])

                tras.append(tra)

                rct_idxs = rct_idxs_
                prd_idxs = prd_idxs_

    tras = tuple(tras)
    print ('tras test:', tras)
    print ('idxs test:', rct_idxs, prd_idxs)
    # import sys
    # sys.exit()
    return tras, rct_idxs, prd_idxs


def _partial_hydrogen_abstraction(qh_gra, q_gra):
    rets = []

    h_atm_key = max(atom_keys(q_gra)) + 1
    uns_atm_keys = unsaturated_atom_keys(q_gra)
    for atm_key in uns_atm_keys:
        q_gra_h = add_atom_explicit_hydrogen_keys(
            q_gra, {atm_key: [h_atm_key]})
        inv_atm_key_dct = full_isomorphism(q_gra_h, qh_gra)
        if inv_atm_key_dct:
            qh_q_atm_key = inv_atm_key_dct[atm_key]
            qh_h_atm_key = inv_atm_key_dct[h_atm_key]
            q_q_atm_key = atm_key
            rets.append((qh_q_atm_key, qh_h_atm_key, q_q_atm_key))

    return rets


def addition(rct_gras, prd_gras):
    """ find an addition transformation

    Additions are identified by joining an unsaturated site on one reactant to
    an unsaturated site on the other. If the result matches the products, this
    is an addition reaction.
    """
    _assert_is_valid_reagent_graph_list(rct_gras)
    _assert_is_valid_reagent_graph_list(prd_gras)

    tras = []
    rct_idxs = None
    prd_idxs = None

    if len(rct_gras) == 2 and len(prd_gras) == 1:
        x_gra, y_gra = rct_gras
        prd_gra, = prd_gras
        x_atm_keys = unsaturated_atom_keys(x_gra)
        y_atm_keys = unsaturated_atom_keys(y_gra)
        for x_atm_key, y_atm_key in itertools.product(x_atm_keys, y_atm_keys):
            xy_gra = add_bonds(
                union(x_gra, y_gra), [{x_atm_key, y_atm_key}])

            atm_key_dct = full_isomorphism(xy_gra, prd_gra)
            if atm_key_dct:
                tra = trans.from_data(frm_bnd_keys=[{x_atm_key, y_atm_key}],
                                      brk_bnd_keys=[])
                tras.append(tra)

                # sort the reactants so that the largest species is first
                rct_idxs = _argsort_reactants(rct_gras)
                prd_idxs = (0,)

    tras = tuple(tras)
    return tras, rct_idxs, prd_idxs


def beta_scission(rct_gras, prd_gras):
    """ find a beta scission transformation

    Implemented as the reverse of an addition reaction.
    """
    tras = []

    rev_tras, prd_idxs, rct_idxs = addition(prd_gras, rct_gras)
    if rev_tras:
        rct_gra = union_from_sequence(rct_gras)
        prd_gra = union_from_sequence(prd_gras)
        tras = [trans.reverse(tra, prd_gra, rct_gra) for tra in rev_tras]

    tras = tuple(set(tras))
    return tras, rct_idxs, prd_idxs


def elimination(rct_gras, prd_gras):
    """ find an elimination transformation

    Eliminations are identified by breaking two bonds from the reactant,
    forming three fragments. This will form one "central fragment" with two
    break sites and two "end fragments" with one break site each. If the
    central fragment plus the two end fragments, joined at their break sites,
    matches the products, this is an elimination reaction.
    """
    _assert_is_valid_reagent_graph_list(rct_gras)
    _assert_is_valid_reagent_graph_list(prd_gras)

    tras = []
    rct_idxs = None
    prd_idxs = None

    if len(rct_gras) == 1 and len(prd_gras) == 2:
        rct_gra, = rct_gras
        rct_bnd_keys = bond_keys(rct_gra)
        # Loop over pairs of bonds and break them. Then, if this forms three
        # fragments, join the two end fragments and compare the result to the
        # products.
        for brk_bnd_key1, brk_bnd_key2 in itertools.combinations(
                rct_bnd_keys, r=2):
            rct_gra_ = remove_bonds(rct_gra, [brk_bnd_key1, brk_bnd_key2])

            # Find the central fragment, which is the one connected to both
            # break sites. If there's a loop there may not be a central
            # fragment, in which case this function will return None.
            cent_frag_atm_keys = _central_fragment_atom_keys(
                rct_gra_, brk_bnd_key1, brk_bnd_key2)
            if cent_frag_atm_keys is not None:
                atm1_key, = brk_bnd_key1 - cent_frag_atm_keys
                atm2_key, = brk_bnd_key2 - cent_frag_atm_keys
                frm_bnd_key = frozenset({atm1_key, atm2_key})

                rct_gra_ = add_bonds(rct_gra_, [frm_bnd_key])

                prd_gra = union_from_sequence(prd_gras)
                atm_key_dct = full_isomorphism(rct_gra_, prd_gra)
                if atm_key_dct:
                    tra = trans.from_data(
                        frm_bnd_keys=[frm_bnd_key],
                        brk_bnd_keys=[brk_bnd_key1, brk_bnd_key2])
                    tras.append(tra)

                    rct_idxs = (0,)

                    cent_prd_atm_keys = frozenset(
                        map(atm_key_dct.__getitem__, cent_frag_atm_keys))

                    if cent_prd_atm_keys <= atom_keys(prd_gras[0]):
                        prd_idxs = (0, 1)
                    else:
                        assert cent_prd_atm_keys <= atom_keys(prd_gras[1])
                        prd_idxs = (1, 0)

    tras = tuple(tras)
    return tras, rct_idxs, prd_idxs


def _central_fragment_atom_keys(gra, brk_bnd_key1, brk_bnd_key2):
    """ Determine atom keys for the central fragment after breaking two bonds.

    The central fragment is the one connected to both break sites.  If there's
    a loop there may not be a central fragment, in which case this function
    will return None.
    """
    gras = connected_components(gra)
    atm_keys = None
    if len(gras) == 3:
        for atm_keys_ in map(atom_keys, gras):
            if (len(brk_bnd_key1 - atm_keys_) == 1 and
                    len(brk_bnd_key2 - atm_keys_) == 1):
                atm_keys = atm_keys_
    return atm_keys


def insertion(rct_gras, prd_gras):
    """ find a insertion transformation

    Implemented as the reverse of an elimination transformation.
    """
    tras = []

    rev_tras, prd_idxs, rct_idxs = elimination(prd_gras, rct_gras)
    if rev_tras:
        rct_gra = union_from_sequence(rct_gras)
        prd_gra = union_from_sequence(prd_gras)
        tras = [trans.reverse(tra, prd_gra, rct_gra) for tra in rev_tras]

    tras = tuple(set(tras))
    return tras, rct_idxs, prd_idxs


def substitution(rct_gras, prd_gras):
    """ find an substitution transformation

    Substitutions are identified by breaking one bond in the reactants and one
    bond from the products and checking for isomorphism.
    """
    _assert_is_valid_reagent_graph_list(rct_gras)
    _assert_is_valid_reagent_graph_list(prd_gras)

    tras = []
    rct_idxs = None
    prd_idxs = None

    if len(rct_gras) == 2 and len(prd_gras) == 2:
        rct_gra = union_from_sequence(rct_gras)
        prd_gra = union_from_sequence(prd_gras)

        rct_bnd_keys = bond_keys(rct_gra)
        prd_bnd_keys = bond_keys(prd_gra)
        for rct_bnd_key, prd_bnd_key in itertools.product(
                rct_bnd_keys, prd_bnd_keys):
            rct_gra_ = remove_bonds(rct_gra, [rct_bnd_key])
            prd_gra_ = remove_bonds(prd_gra, [prd_bnd_key])

            inv_atm_key_dct = full_isomorphism(prd_gra_, rct_gra_)
            if inv_atm_key_dct:
                brk_bnd_key = rct_bnd_key
                frm_bnd_key = frozenset(
                    map(inv_atm_key_dct.__getitem__, prd_bnd_key))

                tra = trans.from_data(
                    frm_bnd_keys=[frm_bnd_key],
                    brk_bnd_keys=[brk_bnd_key])
                tras.append(tra)

                rct_idxs = _argsort_reactants(rct_gras)
                prd_idxs = _argsort_reactants(prd_gras)

    tras = tuple(set(tras))
    return tras, rct_idxs, prd_idxs


REACTION_FINDER_DCT = {
    'HYDROGEN MIGRATION': hydrogen_migration,
    'HYDROGEN ABSTRACTION': hydrogen_abstraction,
    'ADDITION': addition,
    'BETA SCISSION': beta_scission,
    'ELIMINATION': elimination,
    'INSERTION': insertion,
    'SUBSTITUTION': substitution,
}


def classify(rct_gras, prd_gras):
    """ classify a reaction
    """
    rxn_type = None

    for rxn_type, rxn_finder in REACTION_FINDER_DCT.items():
        tras, rct_idxs, prd_idxs = rxn_finder(rct_gras, prd_gras)
        if tras:
            break

    if not tras:
        rxn_type = None

    return tras, rct_idxs, prd_idxs, rxn_type


def _assert_is_valid_reagent_graph_list(gras):
    gras_str = '\n---\n'.join(map(string, gras))
    assert _are_all_explicit(gras), (
        "Implicit hydrogens are not allowed here!\nGraphs:\n{}"
        .format(gras_str))
    assert _have_no_stereo_assignments(gras), (
        "Stereo assignments are not allowed here!\nGraphs:\n{}"
        .format(gras_str))
    assert _have_no_common_atom_keys(gras), (
        "Overlapping atom keys are not allowed here!\nGraphs:\n{}"
        .format(gras_str))


def _are_all_explicit(gras):
    return all(gra == explicit(gra) for gra in gras)


def _have_no_stereo_assignments(gras):
    return all(gra == without_stereo_parities(gra) for gra in gras)


def _have_no_common_atom_keys(gras):
    atm_keys = list(itertools.chain(*map(atom_keys, gras)))
    return len(atm_keys) == len(set(atm_keys))


def _argsort_reactants(gras):

    def __sort_value(args):
        _, gra = args
        val = (-heavy_atom_count(gra),
               -atom_count(gra),
               -electron_count(gra))
        return val

    idxs = tuple(idx for idx, gra in sorted(enumerate(gras), key=__sort_value))
    return idxs
