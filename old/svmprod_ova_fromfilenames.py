#!/usr/bin/python
# -*- coding: utf-8 -*-

""" TODO: docstring """

# TODO: clean it

import optparse
import sys
from os import path
import warnings

import scipy as sp

from scipy import (
    array, io, double, zeros, 
    dot, mean, sign, inf, unique,
    )

from shogun import Kernel, Classifier, Features

# ------------------------------------------------------------------------------
DEFAULT_WEIGHTS = []
DEFAULT_REGULARIZATION = 1e5
DEFAULT_NO_TRACE_NORMALIZATION = False
DEFAULT_OUTPUT_FILENAME = None
DEFAULT_OVERWRITE = False

# ------------------------------------------------------------------------------
def svm_ova_fromfilenames(input_filenames,
                          weights = DEFAULT_WEIGHTS,
                          # --
                          regularization = DEFAULT_REGULARIZATION,
                          no_trace_normalization = DEFAULT_NO_TRACE_NORMALIZATION,
                          # --
                          output_filename = DEFAULT_OUTPUT_FILENAME,
                          overwrite = DEFAULT_OVERWRITE,
                          ):

    """ TODO: docstring """
    assert len(weights) <= len(input_filenames)

    if output_filename is not None:
        # add matlab's extension to the output filename if needed
        if path.splitext(output_filename)[-1] != ".mat":
            output_filename += ".mat"        

        # can we overwrite ?
        if path.exists(output_filename) and not overwrite:
            warnings.warn("not allowed to overwrite %s"  % output_filename)
            return

    # --        
    lw = len(weights)
    lf = len(input_filenames)
    if lw <= lf:
        weights += [1. for _ in xrange(lf-lw)]
    print "Using weights =", weights

    # -- check


    # -- 
    kernel_train = None
    kernel_test = None
    train_fnames = None
    test_fnames = None
    print "Loading %d file(s) ..."  % lf
    for fname, weight in zip(input_filenames, weights):

        print " %s (weight=%f)"  % (fname, weight)

        if weight == 0:
            continue

        kernel_mat = io.loadmat(fname)


        # -- check that kernels come from the same "source"
        if train_fnames is None:
            train_fnames = kernel_mat["train_fnames"]
            test_fnames = kernel_mat["test_fnames"]
        else:
            assert (train_fnames == kernel_mat["train_fnames"]).all()
            assert (test_fnames == kernel_mat["test_fnames"]).all()

        ktrn = kernel_mat['kernel_traintrain']
        ktst = kernel_mat['kernel_traintest']

        if not no_trace_normalization:
            ktrn_trace = ktrn.trace()
            ktrn /= ktrn_trace
            ktst /= ktrn_trace

        ktrn = sp.log(ktrn)/len(weights)
        ktst = sp.log(ktst)/len(weights)

        if kernel_train is None:
            kernel_train = weight * ktrn
            kernel_test = weight * ktst
        else:
            kernel_train += weight * ktrn
            kernel_test += weight * ktst

    ktrn = sp.exp(ktrn)
    ktst = sp.exp(ktst)

    print ktrn

    train_labels = array([str(elt) for elt in kernel_mat["train_labels"]])
    test_labels = array([str(elt) for elt in kernel_mat["test_labels"]])
    #for trnfn in kernel_mat["train_fnames"]:
    #    for tstfn in kernel_mat["test_fnames"]:
    #        assert(trnfn != tstfn)

    # XXX: clean this!!!

    n_categories = len(unique(train_labels))
    
    if not no_trace_normalization:
        kernel_train_trace = kernel_train.trace()
        kernel_train /= kernel_train_trace
        kernel_test /= kernel_train_trace

    kernel_train = kernel_train.astype(double)
    kernel_test = kernel_test.astype(double)

    n_test = kernel_test.shape[1]
    alphas = {}
    support_vectors = {}
    biases = {}
    customkernel = Kernel.CustomKernel()

    customkernel.set_full_kernel_matrix_from_full(kernel_train)

    
    cat_index = {}
    
    # -- train
    categories = unique(train_labels)
    if categories.size == 2:
        categories = [categories[0]]

    for icat, cat in enumerate(categories):
        ltrain = zeros((train_labels.size))
        ltrain[train_labels != cat] = -1
        ltrain[train_labels == cat] = +1
        ltrain = ltrain.astype(double)
        current_labels = Features.Labels(ltrain)
        svm = Classifier.LibSVM(regularization, 
                                customkernel, 
                                current_labels)
        #print svm
        assert(svm.train())
        #print svm
        alphas[cat] = svm.get_alphas()
        svs = svm.get_support_vectors()
        support_vectors[cat] = svs
        biases[cat] = svm.get_bias()
        cat_index[cat] = icat 

    #print "ok"
    
    # -- test
    pred = zeros((n_test))
    distances = zeros((n_test, len(categories)))
    for icat, cat in enumerate(categories):        
        for point in xrange(n_test):
            index_sv = support_vectors[cat]
            resp = dot(alphas[cat], 
                       kernel_test[index_sv, point]) \
                       + biases[cat]

            distances[point, icat] = resp

    if len(categories) > 1:
        pred = distances.argmax(1)
        gt = array([cat_index[e] for e in test_labels]).astype("int")
        perf = (pred == gt)

        accuracy = 100.*perf.sum() / n_test
    else:
        pred = sign(distances).ravel()
        gt = array(test_labels)
        cat = categories[0]
        gt[gt != cat] = -1
        gt[gt == cat] = +1
        gt = gt.astype("int")
        perf = (pred == gt)
        accuracy = 100.*perf.sum() / n_test        
        
    print distances.shape
    print "Classification accuracy on test data (%):", accuracy

    svm_labels = gt

    # -- average precision
    # XXX: redo this part to handle other labels than +1 / -1
    ap = 0
    if distances.shape[1] == 1:
        distances = distances.ravel()
        assert test_labels.ndim == 1            
        assert svm_labels.ndim == 1
    
        # -- inverse predictions if needed
        # (that is when svm was trained with flipped +1/-1 labels)
        # -- convert test_labels to +1/-1 (int)
        try:
            test_labels = array([int(elt) for elt in test_labels])
            if (test_labels != svm_labels).any():
                distances = -distances

            #if not ((test_labels==-1).any() and (test_labels==1).any()):
            #    test_labels[test_labels!=test_labels[0]] = +1
            #    test_labels[test_labels==test_labels[0]] = -1

            #print test_labels

            # -- convert test_labels to +1/-1 (int)
            test_labels = array([int(elt) for elt in test_labels])

            # -- get average precision
            c = distances
            #print c
            si = sp.argsort(-c)
            tp = sp.cumsum(sp.single(test_labels[si]>0))
            fp = sp.cumsum(sp.single(test_labels[si]<0))
            rec  = tp/sp.sum(test_labels>0)
            prec = tp/(fp+tp)

            #print prec, rec
            #from pylab import *
            #plot(prec, rec)
            #show()

            ap = 0
            rng = sp.arange(0,1.1,.1)
            for th in rng:
                p = prec[rec>=th].max()
                if p == []:
                    p = 0
                ap += p / rng.size

            print "Average Precision:", ap

        except ValueError:
            ap = 0


    # --------------------------------------------------------------------------
    # -- write output file

    if output_filename is not None:
        print "Writing %s ..." % (output_filename)
        # TODO: save more stuff (alphas, etc.)
        data = {"accuracy": accuracy,
                "average_precision":ap,
                "test_distances": distances,
                "test_labels": test_labels,
                "svm_labels": svm_labels,
                }

        io.savemat(output_filename, data)

    return accuracy
    
# ------------------------------------------------------------------------------
def main():

    """ TODO: docstring """    

    usage = "usage: %prog [options] <input_filename1> <input_filename2> <...>"
    
    parser = optparse.OptionParser(usage=usage)
    
    # -- 
    parser.add_option("--weight", "-w",
                      type = "float",
                      dest = "weights",
                      action = "append",
                      default = DEFAULT_WEIGHTS,
                      help = "[default=%default]")

    # -- 
    parser.add_option("--regularization", "-C",
                      type="float",
                      default = DEFAULT_REGULARIZATION,
                      help="[default=%default]")

    parser.add_option("--no_trace_normalization", 
                      action="store_true", 
                      default=DEFAULT_NO_TRACE_NORMALIZATION,
                      help="[default=%default]")
  
    # --
    parser.add_option("--output_filename", "-o",
                      type = "str",
                      metavar = "FILENAME",
                      default = DEFAULT_OUTPUT_FILENAME,
                      help = "output the results in FILENAME(.mat) if not None[default=%default]")

    parser.add_option("--overwrite",
                      default=DEFAULT_OVERWRITE,
                      action="store_true",
                      help="overwrite existing file [default=%default]")

    opts, args = parser.parse_args()

    if len(args) < 1:
        parser.print_help()
    else:
        input_filenames = args[:]
            
        print input_filenames

        svm_ova_fromfilenames(input_filenames,
                              weights = opts.weights,
                              # --
                              regularization = opts.regularization,
                              no_trace_normalization = opts.no_trace_normalization,
                              # --
                              output_filename = opts.output_filename,
                              overwrite = opts.overwrite,
                              )
                       
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    main()






