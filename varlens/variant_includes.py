import logging
import time

import pandas
import numpy
import typechecks

import pyfaidx

from . import sequence_context
from . import mhc_binding

class Includeable(object):
    columns = None

    @classmethod
    def from_args(cls, args):
        return cls()

    def process_chunk(self, df):
        raise NotImplementedError()

    def init(self, df):
        pass

    def compute(self, df, chunk_rows=None):
        for column in self.columns:
            if column not in df.columns:
                df[column] = numpy.nan
        rows_to_annotate = pandas.isnull(df[self.columns[0]])
        for column in self.columns[1:]:
            rows_to_annotate = rows_to_annotate | pandas.isnull(df[column])

        self.init(df)

        while rows_to_annotate.sum() > 0:
            if chunk_rows:
                this_chunk_rows = rows_to_annotate & (
                    rows_to_annotate.cumsum() <= chunk_rows)
            else:
                this_chunk_rows = rows_to_annotate

            logging.info("%s: %d / %d rows remaining. Processing %d rows." % (
                self.name,
                rows_to_annotate.sum(),
                len(rows_to_annotate),
                this_chunk_rows.sum()))

            rows_to_annotate = rows_to_annotate & (~ this_chunk_rows)
            
            if this_chunk_rows.sum() > 0:
                start = time.time()
                df.ix[this_chunk_rows, self.columns] = self.process_chunk(
                    df.ix[this_chunk_rows].copy())[self.columns]
                logging.info("Processed in %f0.2 sec" % (time.time() - start))
            yield this_chunk_rows.sum()

class Effect(Includeable):
    name = "variant effect annotations"
    columns = ["effect"]

    @staticmethod
    def add_args(parser):
        parser.add_argument("--include-effect",
            action="store_true", default=False,
            help="Include varcode effect annotations")

    @staticmethod
    def requested(args):
        return args.include_effect

    def process_chunk(self, df):
        df["effect"] = [
            v.effects().top_priority_effect().short_description
            for v in df["variant"]
        ]
        return df

class Gene(Includeable):
    name = "gene annotations"
    columns = ["gene"]
    
    @staticmethod
    def add_args(parser):
        parser.add_argument("--include-gene",
            action="store_true", default=False,
            help="Include gene names")

    @staticmethod
    def requested(args):
        return args.include_gene

    def process_chunk(self, df):
        df["gene"] = [
            ' '.join(v.gene_names) if v.gene_names else 'None'
            for v in df.variant
        ]
        return df

class Context(Includeable):
    name = "variant sequence context"
    columns = ["context_5_prime", "context_3_prime", "context_mutation"]
    
    @staticmethod
    def add_args(parser):
        parser.add_argument("--include-context",
            action="store_true", default=False,
            help="Include variant sequence context")
        parser.add_argument("--reference",
            help="Path to reference fasta (required for sequence context)")
        parser.add_argument("--context-num-bases", type=int, default=15,
            metavar="N",
            help="Num bases of context to include on each side of the variant")

    @classmethod
    def from_args(cls, args):
        return cls(
            reference=pyfaidx.Fasta(args.reference),
            context_num_bases=args.context_num_bases)

    def __init__(self, reference, context_num_bases):
        self.reference = reference
        self.context_num_bases = context_num_bases

    @staticmethod
    def requested(args):
        return args.include_context

    def process_chunk(self, df):
        context_5_prime = []
        context_3_prime = []
        context_mutation = []
        for variant in df.variant:
            tpl = sequence_context.variant_context(
                self.reference,
                variant.contig,
                variant.start,
                variant.end,
                variant.alt,
                self.context_num_bases)
            context_5_prime.append(tpl[0])
            context_mutation.append(tpl[1])
            context_3_prime.append(tpl[2])

        df["context_5_prime"] = context_5_prime
        df["context_3_prime"] = context_3_prime
        df["context_mutation"] = context_mutation
        return df
    
class MHCBindingAffinity(Includeable):
    name = "MHC binding affinity"
    columns = ["binding_affinity", "binding_allele"]

    noncoding_effects = set([
        "intergenic",
        "intronic",
        "non-coding-transcript",
        "3' UTR",
        "5' UTR",
        "silent",
    ])
    
    @staticmethod
    def add_args(parser):
        parser.add_argument("--include-mhc-binding",
            action="store_true", default=False,
            help="Include MHC binding (tightest affinity and allele)")
        parser.add_argument("--hla",
            help="Space separated list of MHC alleles, e.g. 'A:02:01 A:02:02'")
        parser.add_argument('--hla-file',
            help="Load HLA types from the specified CSV file. It must have "
            "columns: 'donor' and 'hla'")

    @classmethod
    def from_args(cls, args):
        return cls(
            hla=args.hla,
            hla_dataframe=(
                pandas.read_csv(args.hla_file) if args.hla_file else None))

    @staticmethod
    def string_to_hla_alleles(s):
        return s.replace("'", "").split()

    def __init__(self, hla=None, hla_dataframe=None, donor_to_hla=None):
        """
        Specify exactly one of hla, hla_dataframe, or donor_to_hla.

        Parameters
        -----------
        hla : list of string
            HLA alleles to use for all donors

        hla_dataframe : pandas.DataFrame with columns 'donor' and 'hla'
            DataFrame giving HLA alleles for each donor. The 'hla' column
            should be a space separated list of alleles for that donor.

        donor_to_hla : dict of string -> string list
            Map from donor to HLA alleles for that donor.
        """
        if sum(x is not None for x in [hla, hla_dataframe, donor_to_hla]) != 1:
            raise TypeError(
                "Specify exactly one of hla, hla_dataframe, donor_to_hla")
        
        self.hla = (
            self.string_to_hla_alleles(hla) if typechecks.is_string(hla)
            else hla)
        self.donor_to_hla = donor_to_hla
        if hla_dataframe is not None:
            self.donor_to_hla = {}
            for (i, row) in hla_dataframe.iterrows():
                if row.donor in self.donor_to_hla:
                    raise ValueError("Multiple rows for donor: %s" % row.donor)
                if pandas.isnull(row.hla):
                    self.donor_to_hla[row.donor] = None
                else:
                    self.donor_to_hla[row.donor] = self.string_to_hla_alleles(
                        row.hla)
        assert self.hla is not None or self.donor_to_hla is not None

    @staticmethod
    def requested(args):
        return args.include_mhc_binding

    def process_chunk(self, df):
        drop_donor = False
        if 'donor' not in df:
            df["donor"] = "DONOR1"
            drop_donor = True
        for donor in df.donor.unique():
            rows = (df.donor == donor)
            if 'effect' in df:
                rows = rows & (~df.effect.isin(self.noncoding_effects))
            sub_df = df.loc[rows]
            alleles = self.hla if self.hla else self.donor_to_hla.get(donor)
            if alleles and sub_df.shape[0] > 0:
                result = mhc_binding.binding_affinities(
                    sub_df.variant, alleles)
                df.loc[rows, "binding_affinity"] = (
                    result["binding_affinity"].values)
                df.loc[rows, "binding_allele"] = (
                    result["binding_allele"].values)
        if drop_donor:
            del df["donor"]
        return df
    
INCLUDEABLES = Includeable.__subclasses__()