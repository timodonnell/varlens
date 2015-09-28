'''
Given genomic loci (e.g. from a VCF file) and one or more BAM files, write a
csv file giving read counts for each allele at each locus.

Note that the output of this command is given in *interbase coordinates*, i.e.
starting at 0, inclusive on first index, exclusive on second.

%(prog)s \
    --reads /path/to/bam1
    --reads /path/to/bam2
    --variants /path/to/first.vcf
    --variants /path/to/second.vcf

'''
from __future__ import absolute_import

import argparse
import csv
import sys
import logging

from .. import load_loci
from .. import load_reads

parser = argparse.ArgumentParser(usage=__doc__)
load_loci.add_args(parser)
load_reads.add_args(parser)

parser.add_argument("--out", required=True)
parser.add_argument("-v", "--verbose", action="store_true", default=False)

def run(raw_args=sys.argv[1:]):
    args = parser.parse_args(raw_args)

    loci = load_loci.load(args)
    if not loci:
        parser.error("No genomic loci (e.g. VCF files) specified.")

    logging.info("Loaded %d genomic loci." % len(loci))

    read_sources = load_reads.load(args)

    with open(args.out, "w") as fd:
        writer = csv.writer(fd)
        writer.writerow([
            "source",
            "contig",
            "interbase_start",
            "interbase_end",
            "allele",
            "count",
        ])
        for source in read_sources:
            logging.info("Reading from: %s" % source.name)
            for locus in loci:
                summary = dict(source.pileups([locus]).allele_summary(locus))
                for (allele, count) in summary.items():
                    writer.writerow([
                        source.name,
                        locus.contig,
                        str(locus.start),
                        str(locus.end),
                        allele,
                        str(count),
                    ])

    logging.info("Wrote: %s" % args.out)
