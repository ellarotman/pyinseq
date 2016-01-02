#!/usr/bin/env python
"""Main script for running the pyinseq package."""

import argparse
import os
from shutil import copyfile
import sys
from demultiplex import sample_prep, demultiplex_fastq, trim_fastq
from gbkconvert import gbk2fna, gbk2ftt
from mapReads import bowtieBuild, bowtieMap
from processMapping import mapSites, mapGenes, buildGeneTable
from utils import convert_to_filename, createExperimentDirectories


def parseArgs(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('-i',
                        '--input',
                        help='input Illumina reads file',
                        required=True)
    parser.add_argument('-s',
                        '--samples',
                        help='sample list with barcodes',
                        required=True)
    parser.add_argument('-e',
                        '--experiment',
                        help='experiment name (no spaces or special characters)',
                        required=True)
    parser.add_argument('-g',
                        '--genome',
                        help='genome in GenBank format (one concatenated file for multiple contigs/chromosomes)',
                        required=True)
    parser.add_argument('-d',
                        '--disruption',
                        help='fraction of gene disrupted (0.0 - 1.0)',
                        default=1.0)
    parser.add_argument('--nobarcodes',
                        help='barcodes have already been removed from the samples; \
                        -i should list the directory with filenames (.fastq.gz) \
                        corresponding to the sample names',
                        action='store_true',
                        default=False)
    return parser.parse_args(args)


class cd:

    """Change to the current working directory, then back."""

    def __init__(self, newPath):
        self.newPath = os.path.expanduser(newPath)

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.savedPath)


def main():
    """Start here."""
    args = parseArgs(sys.argv[1:])
    gbkfile = args.genome
    experiment = convert_to_filename(args.experiment)
    reads = args.input
    samples = args.samples
    # TODO(Test that disruption is between 0.0 and 1.0 (or absent, default 1.0))
    disruption = float(args.disruption)
    nobarcodes = args.nobarcodes

    # Lookup files generated will be called 'genome.fna' etc
    organism = 'genome'

    # pyinseqDirectory = os.getcwd()
    genomeDir = '{experiment}/genome_lookup/'.format(experiment=experiment)

    # Note: barcode length hardcoded at 4 bp here
    barcode_qc, barcode_length = True, 4
    if nobarcodes:
        barcode_qc, barcode_length = False, 0

    # samples dictionary
    # samples = OrderedDict([('name1', {'name': 'name1', 'barcode': 'barcode1'}),
    #    ('name2', {'name': 'name2', 'barcode': 'barcode2'})])
    samplesDict = sample_prep(samples, barcode_qc)

    # Create the directory struture based on the experiment name
    createExperimentDirectories(experiment)

    # add 'demultiplexedPath' and 'trimmedPath' fields for each sample
    for sample in samplesDict:
        demultiplexedPath = '{experiment}/raw_data/{sampleName}.fastq.gz'.format(
            experiment=experiment,
            sampleName=samplesDict[sample]['name'])
        trimmedPath = '{experiment}/{sampleName}_trimmed.fastq'.format(
            experiment=experiment,
            sampleName=samplesDict[sample]['name'])
        samplesDict[sample]['demultiplexedPath'] = demultiplexedPath
        samplesDict[sample]['trimmedPath'] = trimmedPath

    if nobarcodes:
        # copy reads files into the experiment/raw_data directory
        for sample in samplesDict:
            # makes sure the reads directory has a trailing slash
            if reads[-1] != '/':
                reads += '/'
            src = reads + sample + '.fastq.gz'
            dst = samplesDict[sample]['demultiplexedPath']
            copyfile(src, dst)
    else:
        # demultiplex based on barcodes defined in the sample file
        demultiplex_fastq(reads, samplesDict, experiment)

    # Prepare genome files from the GenBank input
    gbk2fna(gbkfile, organism, genomeDir)
    gbk2ftt(gbkfile, organism, genomeDir)

    # Change directory, build bowtie indexes, change directory back
    with cd(genomeDir):
        bowtieBuild(organism)

    # Dictionary of each sample's cpm by gene
    geneMappings = {}
    for sample in samplesDict:
        s = samplesDict[sample]
        trim_fastq(s['demultiplexedPath'], s['trimmedPath'], sample, barcode_length)
        # Change directory, map to bowtie, change directory back
        trimmedSampleFile = '{0}_trimmed.fastq'.format(sample)
        bowtieOutputFile = '{0}_bowtie.txt'.format(sample)
        with cd(genomeDir):
            # Paths are relative to the genome_lookup directory
            # from where bowtie is called
            bowtie_in = '../{0}'.format(trimmedSampleFile)
            bowtie_out = '../{0}'.format(bowtieOutputFile)
            # map to bowtie and produce the output file
            bowtieMap(organism, bowtie_in, bowtie_out)
        # Delete trimmed fastq file after writing mapping results
        os.remove(s['trimmedPath'])
        mapSites('{0}/{1}'.format(experiment, bowtieOutputFile))
        # Add gene-level results for the sample to geneMappings
        # Filtered on gene fraction disrupted as specified by -d flag
        geneMappings[sample] = mapGenes(organism, sample, disruption, experiment)
    buildGeneTable(organism, samplesDict, geneMappings, experiment)

if __name__ == '__main__':
    main()
