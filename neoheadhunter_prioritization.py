import argparse,copy,csv,getopt,logging,multiprocessing,os,sys,subprocess # ,os
import pandas as pd
import numpy as np
from Bio import pairwise2
from Bio.SubsMat import MatrixInfo as matlist
from Bio.SeqIO.FastaIO import SimpleFastaParser
from math import log, exp

import pysam

class Paramset:
    def __init__():
        self.t0Abundance = 33
        self.t0Agretopicity = 0.1
        self.t0Foreignness = 1e-16
        self.t1Abundance = 10
        self.t1BindAff   = 34
        self.t1BindStab  = 1.4
        self.t2Abundance = 11/11
        self.t2BindAff   = 34*11
        self.t2BindStab = 1.4/11
        self.snvindel_location_param = -0.5
        self.non_snvindel_location_param = -1.5
        prior_weight = 1

def isna(arg): return arg in [None, '', 'NA', 'Na', 'None', 'none', '.']

def get_avg_depth_from_rna_depth_filename(rna_depth):
    regsize = -1
    sumDP = -1
    with open(rna_depth) as file:
        for i, line in enumerate(file):
            #sumDP, regsize = line.split('\t')
            if line.startswith('exome_total_bases'): regsize = int(line.split()[1])
            if line.startswith('exome_total_depth'): sumDP   = int(line.split()[1])
    assert regsize > -1
    assert sumDP > -1
    return float(sumDP) / float(regsize)

# Result using this measure is dependent on RNA-seq read length, so it is not recommended to use it (and hence not used).
def get_total_transcript_num_from_rna_flagstat_filename(rna_flagstat):    
    prim_mapped = -1
    prim_duped = -1
    with open(rna_flagstat) as file:
        for line in file:
            pass_nreads, fail_nreads, desc = line.split('\t')
            desc = desc.strip()
            if desc == 'primary mapped': prim_mapped = int(pass_nreads)
            if desc == 'primary duplicates': prim_duped = int(pass_nreads)
    assert prim_mapped >=0, F'The key <primary mapped> is absent in the file {rna_flagstat}'
    assert prim_duped >=0, F'The key <primary duplicates> is absent in the file {rna_flagstat}'
    return prim_mapped - prim_duped
    
# Please note that ref2 is not used in identity check
def var_vcf2vep(vcfrecord):
    def replace_emptystring_by_dash(ch): return (ch if (0 < len(ch)) else '-')
    chrom, pos, ref, alts = (vcfrecord.chrom, vcfrecord.start, vcfrecord.ref, vcfrecord.alts)
    alts = [a for a in alts if not a.startswith('<')]
    if not alts: return (F'{chrom}_{pos}_-/-', -1, -1, -1)
    pos = int(pos)
    alts_len = min([len(alt) for alt in alts])
    i = 0
    while i < len(ref) and i < alts_len and all([(ref[i] == alt[i]) for alt in alts]): i += 1
    chrom2 = chrom
    pos2 = pos + i + 1
    ref2 = replace_emptystring_by_dash(ref[i:])
    alt2 = '/'.join([replace_emptystring_by_dash(alt[i:]) for alt in alts])
    assert ((('tAD' in vcfrecord.info) and len(vcfrecord.info['tAD']) == 2) 
            or (('diRDm' in vcfrecord.info) and len(vcfrecord.info['diRDm']) == 1 and
                ('diADm' in vcfrecord.info) and len(vcfrecord.info['diADm']) == 1))
    refAD = (vcfrecord.info['tAD'][0] if ('tAD' in vcfrecord.info) else vcfrecord.info['diRDm'][0])
    tumorAD = (vcfrecord.info['tAD'][1] if ('tAD' in vcfrecord.info) else vcfrecord.info['diADm'][0])
    return ('_'.join([chrom2, str(pos2), ref2 + '/' + alt2]), vcfrecord.qual, int(refAD), int(tumorAD)) # tumor allele depths

def vep_lenient_equal(vep1, vep2):
    chrom1, pos1, alleles1 = vep1.split('_')
    alleles1 = alleles1.split('/')
    chrom2, pos2, alleles2 = vep2.split('_')
    alleles2 = alleles2.split('/')
    if chrom1 == chrom2 and pos1 == pos2:
        alen = min((len(alleles1), len(alleles2)))
        for alt1 in alleles1[1:]:
            for alt2 in alleles2[1:]:
                ref1 = alleles1[0]
                ref2 = alleles2[0]
                if ref1[0] == ref2[0] and alt1[0] == alt2[0]:
                    return True
    return False

def getR(neo_seq,iedb_seq): 
    align_score = []
    a = 26
    k = 4.86936
    for seq in iedb_seq:
        aln_score = aligner(neo_seq,seq)
        if aln_score:            
            localds_core = max([line[2] for line in aln_score])
            align_score.append(localds_core)

    bindingEnergies = list(map(lambda x: -k * (a - x), align_score))
    ## This tweak ensure that we get similar results compared with antigen.garnish at
    ## https://github.com/andrewrech/antigen.garnish/blob/main/R/antigen.garnish_predict.R#L86
    # bindingEnergies = [max(bindingEnergies)] 
    sumExpEnergies = sum([exp(x) for x in bindingEnergies])
    Zk = (1 + sumExpEnergies)
    return float(sumExpEnergies) / Zk

def getiedbseq(iedb_path):
    iedb_seq = []
    with open(iedb_path, 'r') as fin: #'/data8t_2/zzt/antigen.garnish/iedb.fasta'
        for t, seq in SimpleFastaParser(fin):
            iedb_seq.append(seq)
    return iedb_seq

def iedb_fasta_to_dict(iedb_path):
    ret = {}
    with open(iedb_path, 'r') as iedb_fasta_file:
        for fasta_id, fasta_seq in SimpleFastaParser(iedb_fasta_file):
            if fasta_id in ret:
                assert fasta_seq == ret[fasta_id], F'The FASTA_ID {fasta_id} is duplicated in the file {iedb_path}'
            ret[fasta_id] = fasta_seq
    return ret

def aligner(seq1,seq2):
    matrix = matlist.blosum62
    gap_open = -11
    gap_extend = -1
    aln = pairwise2.align.localds(seq1.upper(), seq2.strip().split('+')[0].upper(), matrix, gap_open, gap_extend)
    return aln
    
def write_file(a_list, name):
    textfile = open(name, "w")
    for element in a_list:
        textfile.write(element + "\n")
    textfile.close()

##########Calculate wild type binding affinity###########
# def mutation_netmhc(prefix, netmhc_path, input_folder, output_directory, hla):
#     run_netmhc = netmhc_path+" -a "+hla+" -f "+input_folder+"/"+prefix+"_snv_indel_wt.fasta -l '8,9,10,11' -BA > "+output_directory+"/tmp_netmhc/"+hla+"_wt_tmp_hla_netmhc.txt"
#     print(run_netmhc)
#     subprocess.call(run_netmhc, shell=True, executable="/bin/bash")

# def mutation_netmhc_parallel(prefix, netmhc_path, input_folder, output_directory, hla_str):
#     os.system("mkdir "+output_directory+"/tmp_netmhc")
#     hla_list = list(hla_str.strip().split(","))
#     netmhc_hla_process=[]
#     for hla in hla_list:
#         run_netmhc = multiprocessing.Process(target=mutation_netmhc,args=(prefix, netmhc_path, input_folder, output_directory, hla))#"./netmhc_parallel.sh "+netmhc_path+" "+output_directory+" "+hla
#         netmhc_hla_process.append(run_netmhc)
#     for p in netmhc_hla_process:
#         p.daemon = True
#         p.start()
#     for p in netmhc_hla_process:
#         p.join()
#     os.system("cat "+output_directory+"/tmp_netmhc/* > "+output_directory+"/"+prefix+"_snv_indel_wt_netmhc.csv")

def get_wt_bindaff(wt_seq,hla,output_directory,netmhc_cmd):
    os.system("mkdir "+output_directory+"/tmp")
    with open(output_directory+"/tmp/wt.pep", "w") as pepfile:
        pepfile.write(wt_seq)
    pepfile.close()
    args = netmhc_cmd+" -p "+output_directory+"/tmp/wt.pep -a "+ hla+" -l "+str(len(wt_seq))+" -BA >> "+output_directory+"/tmp/wt.csv"
    subprocess.call(args, shell=True)  
    wt_bindaff = 1
    with open(output_directory+"/tmp/wt.csv") as f:
        data = f.read()
    nw_data = data.split('-----------------------------------------------------------------------------------\n')
    for i in range(len(nw_data)):
        if i%4 == 2:
            wt_bindaff = nw_data[i].strip().split()[15]
            break
    os.system("rm -rf "+output_directory+"/tmp")
    return wt_bindaff

def runblast(query_seq, target_fasta, output_directory):
    os.system(F'mkdir -p {output_directory}/tmp')
    query_fasta = F'{output_directory}/tmp/foreignness_query.{query_seq}.fasta'
    with open(query_fasta, 'w') as query_fasta_file:
        query_fasta_file.write(F'>{query_seq}\n{query_seq}\n')
    # from https://github.com/andrewrech/antigen.garnish/blob/main/R/antigen.garnish_predict.R
    cmd = F'''blastp \
        -query {query_fasta} -db {target_fasta} \
        -evalue 100000000 -matrix BLOSUM62 -gapopen 11 -gapextend 1 \
        -out {query_fasta}.blastp_iedbout.csv -num_threads 8 \
        -outfmt '10 qseqid sseqid qseq qstart qend sseq sstart send length mismatch pident evalue bitscore' '''
    logging.debug(cmd)
    os.system(cmd)
    ret = []
    with open(F'{query_fasta}.blastp_iedbout.csv') as blastp_csv:
        for line in blastp_csv:
            tokens = line.strip().split(',')
            sseq = tokens[5]
            is_canonical = all([(aa in 'ARNDCQEGHILKMFPSTWYV') for aa in sseq])
            if is_canonical: ret.append(sseq)
    return ret

def indicator(x): return np.where(x, 1, 0)
def compute_immunogenic_probs(data, paramset):
    
    t2BindAff      = paramset.binding_affinity_hard_thres
    t1BindAff      = paramset.binding_affinity_soft_thres
    
    t2BindStab     = paramset.binding_stability_hard_thres
    t1BindStab     = paramset.binding_stability_soft_thres
    
    t2Abundance    = paramset.tumor_abundance_hard_thres
    t1Abundance    = paramset.tumor_abundance_soft_thres
    
    t0Abundance    = paramset.tumor_abundance_recognition_thres
    t0Agretopicity = paramset.agretopicity_thres
    t0Foreignness  = paramset.foreignness_thres
     
    snvindel_location_param     = paramset.snvindel_location_param
    non_snvindel_location_param = paramset.non_snvindel_location_param
    prior_weight                = paramset.immuno_strength_null_hypothesis_prior_weight
    
    are_snvs_or_indels_bool = (data.Identity.isin(['SNV', 'INS', 'DEL', 'INDEL']))
    are_snvs_or_indels = indicator(are_snvs_or_indels_bool)
    
    t0foreign_nfilters = indicator(np.logical_and((t0Foreignness > data.Foreignness), (t0Agretopicity < data.Agretopicity)))
    t0recognized_nfilters = (
        indicator(data.BindAff > t1BindAff) +
        indicator(data.BindStab < t1BindStab) +
        indicator(data.Quantification < t0Abundance) + 
        t0foreign_nfilters)
    t1presented_nfilters = (
        indicator(data.BindAff > t1BindAff) +
        indicator(data.BindStab < t1BindStab) +
        indicator(data.Quantification < t1Abundance)) 
    t2presented_nfilters = (
        indicator(data.BindAff > t2BindAff) +
        indicator(data.BindStab < t2BindStab) +
        indicator(data.Quantification < t2Abundance))
    
    t0_are_foreign = (t0foreign_nfilters == 0)
    #t1_are_bound = indicator((data.BindAff <= t1BindAff) & (data.BindStab >= t1BindStab))
    t1_are_presented = (t1presented_nfilters == 0)
    presented_not_recog = t1_are_presented * are_snvs_or_indels * indicator(t0foreign_nfilters >  0)
    presented_and_recog = t1_are_presented * are_snvs_or_indels * indicator(t0foreign_nfilters == 0)
    presented_not_recog_burden = sum(data.RNA_normAD * presented_not_recog)
    presented_and_recog_burden = sum(data.RNA_normAD * presented_and_recog)
    prior_avg_burden = (presented_and_recog_burden + presented_not_recog_burden + 0.5) / (sum(presented_not_recog) + sum(presented_and_recog) + 1)
    presented_and_recog_avg_burden = (prior_avg_burden * prior_weight + presented_and_recog_burden) / (prior_weight + sum(presented_and_recog))
    presented_not_recog_avg_burden = (prior_avg_burden * prior_weight + presented_not_recog_burden) / (prior_weight + sum(presented_not_recog))
    # The variable immuno_strength should be positive/negative for patients with low/high immune strength
    immuno_strength = log(presented_not_recog_avg_burden / presented_and_recog_avg_burden) * 2 
    
    # Please be aware that t2presented_nfilters should be zero if the data were hard-filtered with t2 thresholds first. 
    log_odds_ratio = (t1BindAff / (t1BindAff + data.BindAff)
            + np.minimum(1 - t0recognized_nfilters + immuno_strength, 1)
            - t1presented_nfilters 
            - (t2presented_nfilters * 3) 
            + (are_snvs_or_indels * snvindel_location_param) + (1 - are_snvs_or_indels) * non_snvindel_location_param)
    p = 1 / (1 + np.exp(-log_odds_ratio))
    return (p, t2presented_nfilters, t1presented_nfilters, t0recognized_nfilters, 
            sum(presented_not_recog), sum(presented_and_recog), 
            presented_not_recog_burden, presented_and_recog_burden, immuno_strength)

def read_tesla_xls(tesla_xls, patientID):
    # cat GRCh37_gencode_v19_CTAT_lib_Mar012021.plug-n-play/ctat_genome_lib_build_dir//ref_annot.gtf.mini.sortu  | awk '{print $NF}' | sort | uniq | wc
    #  57055   57055 1688510 # 57055 genes, so averageTMP = 1e6 / 57055
    df1 = pd.read_excel(tesla_xls)
    df1.PATIENT_ID = df1.PATIENT_ID.astype(int)
    df = df1.loc[df1.PATIENT_ID == patientID,]
    if 'NETMHC_BINDING_AFFINITY' in df.columns:
        df['BindAff'] = df.NETMHC_BINDING_AFFINITY.astype(float)
    elif 'NETMHC_PAN_BINDING_AFFINITY' in df.columns:
        df['BindAff'] = df.NETMHC_PAN_BINDING_AFFINITY.astype(float)
    else:
        sys.stderr.write(F'BindAff is not present in {tesla_xls}')
        exit(1)
    df['BindStab'] = df.BINDING_STABILITY.astype(float)
    df['Quantification'] = df.TUMOR_ABUNDANCE.astype(float)
    df['Agretopicity'] = df.AGRETOPICITY.astype(float)
    df['Foreignness'] = df.FOREIGNNESS.astype(float)
    df['RNA_normAD'] = df.Quantification * 0.02 # 0.02 is empirical
    df['Identity'] = 'SNV' # most neo-epitope candidates are from SNVs
    ret = df.dropna(subset=['BindAff', 'BindStab', 'Quantification', 'Agretopicity', 'Foreignness'])
    return ret
    
def datarank(data, outcsv, paramset):
    
    probs, t2presented_filters, t1presented_filters, t0recognized_filters, \
            n_presented_not_recognized, n_presented_and_recognized, presented_not_recognized_burden, presented_and_recognized_burden, immuno_strength \
            = compute_immunogenic_probs(data, paramset)
    data['Probability'] = probs
    data['PresentationPreFilters'] = t2presented_filters
    data['PresentationFilters'] = t1presented_filters
    data['RecognitionFilters'] = t0recognized_filters
    data["Rank"]=data["Probability"].rank(method="first", ascending=False)

    data=data.sort_values("Rank")
    data=data.astype({"Rank":int})
    data.to_csv(outcsv, header=1, sep='\t', index=0, float_format='%6g', na_rep = 'NA')
    with open(outcsv + ".extrainfo", "w") as extrafile:
        extrafile.write(F'expected_bound_and_immunogenic_pMHC_num={n_presented_and_recognized}\n')
        extrafile.write(F'expected_bound_not_immunogenic_pMHC_num={n_presented_not_recognized}\n')
        extrafile.write(F'expected_bound_and_immunogenic_pMHC_rna_normADsum={presented_and_recognized_burden}\n')
        extrafile.write(F'expected_bound_and_immunogenic_pMHC_rna_normADsum={presented_not_recognized_burden}\n')
        extrafile.write(F'immuno_strength={immuno_strength}\n')
        extrafile.write(F'expected_immunogenic_peptide_num={sum(probs)}\n')
    return data, (n_presented_not_recognized, n_presented_and_recognized, presented_not_recognized_burden, presented_and_recognized_burden, immuno_strength)
    
def main():
    description = 'This script computes the probability that each neoantigen candidate is validated to be immunogenic (i.e., true positive). '
    epilog = '''
Hard thresholds should be much less strict than soft thresholds. 
If (output_directory, tesla_xls, tesla_patientID) are set, 
    then (input_folder, iedb_fasta, netmhc_cmd, alteration_type) are all irrelevant and therefore unused.
If the keyword rerank is in function,
    then (iedb_fasta, netmhc_cmd, alteration_type) are all irrelevant and therefore unused. '''.strip()
    
    parser = argparse.ArgumentParser(description = description, epilog = epilog, formatter_class = argparse.ArgumentDefaultsHelpFormatter)
    
    parser.add_argument('-i', '--input-directory', help = 'input directory containing result file from binding-stability prediction', required = True)
    parser.add_argument('-I', '--iedb-fasta', help = 'path to IEDB reference fasta file containing pathogen-derived immunogenic peptides', required = True)
    parser.add_argument('-o', '--output-directory', help = 'output directory to store result', required = True)
    parser.add_argument('-p', '--prefix', help = 'prefix of the oupput files in the output directory', required = True)
    parser.add_argument('-n', '--netmhcpan-cmd', help = 'command to run the netmhcpan program', required = True)
    
    parser.add_argument('-t', '--alteration-type', default = 'snv,indel,fusion,splicing',
            help = 'type of alterations detected, can be a combination of (snv, indel, sv, and/or fusion separated by comma)')
    parser.add_argument('--binding-affinity-hard-thres', default = 34.0*11, type=float,
            help = 'hard threshold of peptide-MHC binding affinity to predict peptide-MHC presentation to cell surface')
    parser.add_argument('--binding-affinity-soft-thres', default = 34.0, type=float,
            help = 'soft threshold of peptide-MHC binding affinity to predict peptide-MHC presentation to cell surface')
    parser.add_argument('--binding-stability-hard-thres', default = round(1.4/11,3), type=float,
            help = 'hard threshold of peptide-MHC binding stability to predict peptide-MHC presentation to cell surface')
    parser.add_argument('--binding-stability-soft-thres', default = 1.4, type=float,
            help = 'soft threshold of peptide-MHC binding stability to predict peptide-MHC presentation to cell surface')
    parser.add_argument('--tumor-abundance-hard-thres', default = 33.0/3/11, type=float,
            help = 'hard threshold of peptide-MHC binding affinity to predict peptide-MHC recognition by T-cells')
    parser.add_argument('--tumor-abundance-soft-thres', default = 33.0/3, type=float,
            help = 'soft threshold of peptide-MHC binding affinity to predict peptide-MHC recognition by T-cells')
    parser.add_argument('--agretopicity-thres', default = 0.1, type=float,
            help = 'threshold of agretopicity to predict peptide-MHC recognition by T-cells')
    parser.add_argument('--foreignness-thres', default = 1e-16, type=float,
            help = 'threshold of foreignness to predict peptide-MHC recognition by T-cells')
    parser.add_argument('--tumor-abundance-recognition-thres', default = 33.0, type=float,
            help = 'threshold of tumor abundance to predict peptide-MHC recognition by T-cells')
    
    parser.add_argument('--snvindel-location-param', default = -1.5, type=float,
            help = 'location parameter of the logistic regression used to estimate the probability that a peptide-MHC is immunogenic '
            'if the peptide originate from SNVs and InDels. '
            'This parameter does not change the ranking of peptide-MHC immunogenities for peptides originating from SNVs and InDels. ')
    parser.add_argument('--non-snvindel-location-param', default = -2.5, type=float,
            help = 'location parameter of the logistic regression used to estimate the probability that a peptide-MHC is immunogenic '
            'if the peptide does not originate from SNVs and InDels. '
            'This parameter does not change the ranking of peptide-MHC immunogenities for peptides not originating from SNVs and InDels. ')
    
    parser.add_argument('--immuno-strength-null-hypothesis-prior-weight', default = 1.0, type=float,
            help = 'the weight of the prior belief that recognized and non-recognized abundance-agnostic peptides '
            '(without filter by abundance) are equally abundant. '
            'This parameter does not change the ranking of peptide-MHC immunogenities for peptides within the two classes: not recognized and recognized '
            '(a small value for this parameter (for example, 1) can make unrecognized peptides '
            'partially and fully recognized if (immunoStrength>0) and (immunoStrength>0.5), respectively. ')

    parser.add_argument('--dna-vcf', default = '',
            help = 'VCF file (which can be block-gzipped) generated by calling small variants from DNA-seq data')
    parser.add_argument('--rna-vcf', default = '',
            help = 'VCF file (which can be block-gzipped) generated by calling small variants from RNA-seq data')
    parser.add_argument('--rna-depth', default = '',
            help = 'A file containing summary information about RNA fragment depth')

    parser.add_argument('--function', default = '',
            help = 'The keyword rerank means using existing stats (affinity, stability, etc.) to re-rank the neoantigen candidates')
    parser.add_argument('--tesla-xls', default = '',
            help = 'Table S4 and S7 at https://doi.org/10.1016/j.cell.2020.09.015')
    parser.add_argument('--tesla-patientID', default = '',
            help = 'the ID in the PATIENT_ID column to select the rows in --tesla-xls')
    
    args = parser.parse_args()
    paramset = args
    print(paramset)
    
    if not isna(args.tesla_xls):
        data = read_tesla_xls(args.tesla_xls, args.tesla_patientID)
        data2, _ = datarank(data, F'{output_directory}/{prefix}_neoantigen_rank_neoheadhunter.from_tesla_excel.tsv', paramset)
        exit(0)
    if args.function == 'rerank':
        data = pd.read_csv(F'{output_directory}/{prefix}_neoantigen_rank_neoheadhunter.tsv', sep='\t')
        data2, _ = datarank(data, F'{output_directory}/{prefix}_neoantigen_rank_neoheadhunter.rerank.tsv', paramset)
        exit(0) 
    
    input_directory = args.input_directory
    output_directory = args.output_directory
    prefix = args.prefix
    
    wt_pep_to_bindaff = {}
    with open(F'{input_directory}/tmp_identity/{prefix}_bindaff_filtered.tsv') as csvfile:
        tmp_wt_bindaff_file = csv.reader(csvfile, delimiter="\t")
        for line in tmp_wt_bindaff_file:
            if line[7] != "":
                wt_pep_to_bindaff[line[2]] = line[7]
    
    snv_indel_filename = F'{input_directory}/../info/{prefix}_snv_indel.annotation.tsv'
    fusion_filename = F'{input_directory}/../info/{prefix}_fusion.tsv'
    splicing_filename = F'{input_directory}/../info/{prefix}_splicing.csv'
    
    snv_indel_file = open(snv_indel_filename)
    fusion_file = (open(fusion_filename) if os.path.exists(fusion_filename) else [])
    splicing_file = (open(splicing_filename) if os.path.exists(splicing_filename) else [])
     
    dnaseq_small_variants_file = (pysam.VariantFile(args.dna_vcf, 'r') if args.dna_vcf else [])
    rnaseq_small_variants_file = (pysam.VariantFile(args.rna_vcf, 'r') if args.rna_vcf else [])

    snv_indel = [line for line in snv_indel_file]
    fusion = [line for line in fusion_file]
    splicing = [line for line in splicing_file]
    
    if snv_indel_file: snv_indel_file.close()
    if fusion_file: fusion_file.close()
    if splicing_file: splicing_file.close() 

    candidate_file = open(F'{args.input_directory}/{prefix}_candidate_pmhc.csv')
    reader = csv.reader(candidate_file, delimiter=',')
    fields=next(reader)
    fields.append("Foreignness")
    fields.append("Agretopicity")
    fields.append("DNA_QUAL")
    fields.append("DNA_refDP")
    fields.append("DNA_altDP")
    fields.append("RNA_QUAL")
    fields.append("RNA_refDP")
    fields.append("RNA_altDP")
    fields.append("SourceAlterationDetail")
    fields.append('IsFrameshift')
    data_raw = []
    data_exist = [] # save existing hla, mutant_type peptide
    agre_exist = []
    for line1 in reader:
        line = copy.deepcopy(line1)
        blast_iedb_seqs = runblast(line[1], args.iedb_fasta, output_directory)
        R = getR(line[1], blast_iedb_seqs)
        line.append(R)
        mt_bindaff = float(line[3])
        identity = line[5]
        if (("SNV" in identity) or ('INS' in identity) or ('DEL' in identity) or ("INDEL" in identity)) and line[2] in wt_pep_to_bindaff:
            wt_bindaff = wt_pep_to_bindaff[line[2]]
        else:
            wt_bindaff = get_wt_bindaff(line[2],line[0].replace('*',''), output_directory, args.netmhcpan_cmd)
        
        A = mt_bindaff/float(wt_bindaff) 
        if ([line[0],line[1]] in data_exist):
            indices = [i for i, x in enumerate(data_exist) if x == [line[0],line[1]] ]
            for index in indices:
                if (A > agre_exist[index]): # should get the biggest agre (agretopicity)
                    agre_exist[index] = -2 #A
                    data_raw[index][8] = -2 #A
                    logging.info(F'Invalidated previous {line[0]} {line[1]}')
                else:
                    A = -2
        else:
            data_exist.append([line[0],line[1]])
            agre_exist.append(A)
        line.append(A)
        
        dna_varqual = 0
        dna_ref_depth = 0
        dna_alt_depth = 0
        rna_varqual = 0
        rna_ref_depth = 0
        rna_alt_depth = 0
        line_info_string = ""
        is_frameshift = False
        if (identity.strip().split('_')[0] in ["SNV", 'INS', 'DEL', 'INDEL'] or identity.strip().split('_')[0].startswith("INDEL")):
            line_num = int(identity.strip().split('_')[1])
            snv_indel_line = snv_indel[line_num-1]
            ele = snv_indel_line.strip().split('\t')
            if len(ele) == 14: # annotation software is vep
                annotation_info = ["Uploaded_variation","Location","Allele","Gene","Feature","Feature_type",
                                    "Consequence","cDNA_position","CDS_position","Protein_position","Amino_acids","Codons","Existing_variation","Extra"]
                for i in range(0,len(ele),1):
                    line_info_string+=annotation_info[i]+"$"+ele[i]+"#"
                    if annotation_info[i] == 'Consequence' and (ele[i].lower().startswith('frameshift') or ele[i].lower().startswith('frame_shift')):
                        is_frameshift = True
                chrom, pos, alts = ele[0].split('_')
                if dnaseq_small_variants_file:                    
                    for vcfrecord in dnaseq_small_variants_file.fetch(chrom, int(pos) - 6, int(pos) + 6):
                        vepvar, varqual, varRD, varAD = var_vcf2vep(vcfrecord)
                        if vep_lenient_equal(vepvar, ele[0]):
                            dna_varqual = max((dna_varqual, varqual))
                            dna_ref_depth = max((dna_ref_depth, varRD))
                            dna_alt_depth = max((dna_alt_depth, varAD))
                    #line_info_string += 'DNAseqVariantQuality${}'.format(max_varqual)
                if rnaseq_small_variants_file:
                    for vcfrecord in rnaseq_small_variants_file.fetch(chrom, int(pos) - 6, int(pos) + 6):
                        vepvar, varqual, varRD, varAD = var_vcf2vep(vcfrecord)
                        if vep_lenient_equal(vepvar, ele[0]):
                            rna_varqual = max((rna_varqual, varqual))
                            rna_ref_depth = max((rna_ref_depth, varRD))
                            rna_alt_depth = max((rna_alt_depth, varAD))
            elif len(ele)==11:
                annotation_info = ["CHROM","POS","ID","REF","ALT","QUAL","FILTER","INFO","FORMAT","normal","tumor"]
                for i in range(0,len(ele),1):
                    line_info_string+=annotation_info[i]+"$"+ele[i]+"#"
            else:
                continue
        elif (identity.strip().split('_')[0]=="FUSION"):
            line_num = int(identity.strip().split('_')[1])
            fusion_line = fusion[line_num-1]
            ele = fusion_line.strip().split('\t')
            annotation_info = ["FusionName","JunctionReadCount","SpanningFragCount","est_J","est_S","SpliceType","LeftGene","LeftBreakpoint",
                                "RightGene","RightBreakpoint","LargeAnchorSupport","FFPM","LeftBreakDinuc","LeftBreakEntropy","RightBreakDinuc",
                                "RightBreakEntropy","annots","CDS_LEFT_ID","CDS_LEFT_RANGE","CDS_RIGHT_ID","CDS_RIGHT_RANGE","PROT_FUSION_TYPE",
                                "FUSION_MODEL","FUSION_CDS","FUSION_TRANSL","PFAM_LEFT","PFAM_RIGHT"]
            for i in range(0, len(ele),1):
                line_info_string+=annotation_info[i]+"$"+ele[i]+"#"
        elif (identity.strip().split('_')[0]=="SP"):
            line_num = int(identity.strip().split('_')[1])
            splicing_line = splicing[line_num-1]
            ele = splicing_line.strip().split('\t')
            annotation_info = ["chrom","txStart","txEnd","isoform","protein","strand","cdsStart","cdsEnd","gene","exonNum",
                                "exonLens","exonStarts","ensembl_transcript"]
            for i in range(0, len(ele),1):
                line_info_string+=annotation_info[i]+"$"+ele[i]+"#"
        else:
            continue
        line[5] = identity.strip().split('_')[0]
        line.append(dna_varqual) 
        line.append(dna_ref_depth)
        line.append(dna_alt_depth)
        line.append(rna_varqual)
        line.append(rna_ref_depth)
        line.append(rna_alt_depth)
        line.append(line_info_string)
        line.append(is_frameshift)
        data_raw.append(line)
        
    picked_rows = []
    alt_type = args.alteration_type.replace(' ', '').strip().split(',')
    for line in data_raw:
        atype = line[5].strip().split('_')[0]
        if (atype == 'SP'): atype='SPLICING'
        if atype.lower() in alt_type: picked_rows.append(line)
    # data can be emtpy (https://stackoverflow.com/questions/44513738/pandas-create-empty-dataframe-with-only-column-names)
    data=pd.DataFrame(picked_rows, columns = fields)
    data.BindAff = data.BindAff.astype(float)
    data.BindStab = data.BindStab.astype(float)
    data.Foreignness = data.Foreignness.astype(float)
    data.Agretopicity = data.Agretopicity.astype(float)
    data.Quantification = data.Quantification.astype(float)
    data['RNA_normAD'] = data.RNA_altDP.astype(float) / get_avg_depth_from_rna_depth_filename(args.rna_depth)
    
    # are_highly_abundant is not used because we have too little positive data
    # are_highly_abundant = ((data.BindAff <= 34/10.0) & (data.BindStab >= 1.4*10.0) & (data.Quantification >= 1.0*10))
    # keptdata = data[(data.Quantification >= tumor_RNA_TPM_threshold) & ((~data.is_frameshift) | are_highly_abundant) & (data.Agretopicity > -1)]
    keptdata = data[(data.Agretopicity > -1)]
    
    keptdata.insert(len(keptdata.columns)-1, 'SourceAlterationDetail', keptdata.pop('SourceAlterationDetail'))
    keptdata.drop(['BindLevel'], axis=1)
    data2, _ = datarank(keptdata, F'{output_directory}/{prefix}_neoantigen_rank_neoheadhunter.tsv', paramset)
    
    if dnaseq_small_variants_file: dnaseq_small_variants_file.close()
    if rnaseq_small_variants_file: rnaseq_small_variants_file.close()
    
if __name__ == '__main__':
    main()
