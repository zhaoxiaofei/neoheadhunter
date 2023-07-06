import csv,logging,multiprocessing,os,subprocess
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(message)s')

# hard filters
tumor_depth, tumor_vaf, normal_vaf = (5, 0.1, 0.05)
binding_affinity_thres = 34.0 * 14.0
binding_stability_thres = 1.4 / 14.0
tumor_abundance_thres = 1.0 # transcript-per-million
alteration_type = 'snv,indel,fusion,splicing'

# soft filters
binding_affinity_presentation_thres = 34.0
binding_stability_presentation_thres = 1.4
binding_affinity_recognition_thres = 34.0
binding_stability_recognition_thres = 1.4
agretopicity_recognition_thres = 0.1
foreignness_recognition_thres = 1e-16

script_directory = os.path.dirname(os.path.abspath(sys.argv[0]))
script_basedir = script_directory

# config

RES = config["res"] # output result directory path
PREFIX = config["prefix"]
DNA_TUMOR_FQ1 = config["dna_tumor_fq1"]
DNA_TUMOR_FQ2 = config["dna_tumor_fq2"]
DNA_NORMAL_FQ1 = config["dna_normal_fq1"]
DNA_NORMAL_FQ2 = config["dna_normal_fq2"]
RNA_TUMOR_FQ1 = config["rna_tumor_fq1"]
RNA_TUMOR_FQ2 = config["rna_tumor_fq2"]
CTAT = config["ctat"]
REF = F"{CTAT}/ref_genome.fa"
HLA_REF = config["hla_ref"]

netmhcpan_cmd = '/mnt/d/code/neohunter/netMHCpan-4.1/netMHCpan'
netmhcpan_path = netmhcpan_cmd
netmhcstabpan_cmd = 'ssh://zxf@166.111.130.101:50022/data8t_4/zxf/software/netMHCstabpan-1.0/netMHCstabpan'
netmhcstabpan_path = netmhcstabpan_cmd

vep_exe = '/home/zhaoxiaofei/miniconda3/envs/neohunter-env2/bin/vep'
vep_cache = '/mnt/d/code/neohunter/NeoHunter'
asneo_ref = '/mnt/d/code/neohunter/Neohunter/hg19.fa' # The {CTAT} {REF} does not work with ASNEO
asneo_gtf = '/mnt/d/code/neohunter/Neohunter/hg19.refGene.gtf' # The {CTAT} .gtf does not work with ASNEO

ref_pep_fa = '{script_basedir}/Homo_sapiens.GRCh37.pep.all.fa'


### usually you should not modify the code below (please think twice before doing so) ###

def call_with_infolog(cmd, in_shell = True):
    logging.info(cmd)
    subprocess.call(cmd, shell = in_shell)

DNA_TUMOR_ISPE  = (DNA_TUMOR_FQ2  not in [None, "", "NA", "Na", "None", "none", "."])
DNA_NORMAL_ISPE = (DNA_NORMAL_FQ2 not in [None, "", "NA", "Na", "None", "none", "."])
RNA_TUMOR_ISPE  = (RNA_TUMOR_FQ2  not in [None, "", "NA", "Na", "None", "none", "."])

info_dir = F"{RES}/info/"
neopeptide_dir = F"{RES}/neopeptides"
alignment_dir = F"{RES}/alignments"
snvindel_dir = F"{RES}/snvindels"
pmhc_dir = F"{RES}/pmhcs"
prioritization_dir = F"{RES}/prioritization"

snvindel_info_file = F"{info_dir}/{PREFIX}_snv_indel.annotation.tsv"
fusion_info_file = F"{info_dir}/{PREFIX}_fusion.tsv"
splicing_info_file = F"{info_dir}/{PREFIX}_splicing.tsv"

#def get_hla_typing_result(wildcards):
#    return sorted(glob.glob(wildcards.date + '*_result.tsv'))[-1]

hla_fq_r1 = F"{RES}/hla_typing/{PREFIX}.rna_hla_r1.fastq.gz",
hla_fq_r2 = F"{RES}/hla_typing/{PREFIX}.rna_hla_r2.fastq.gz",
hla_fq_se = F"{RES}/hla_typing/{PREFIX}.rna_hla_se.fastq.gz",
hla_bam   = F"{RES}/hla_typing/{PREFIX}.rna_hla_typing.bam",
hla_out   = F"{RES}/hla_typing/{PREFIX}_hlatype.tsv"
rule hla_typing:
    output:
        out = F"{hla_out}",
    run:
        shell("echo BEGIN hla_typing_helper "
            " && bwa mem -t {workflow.cores} {HLA_REF} {RNA_TUMOR_FQ1} {RNA_TUMOR_FQ2} | samtools view -bh -F4 -o {hla_bam}"
            # Note: razers3 is too memory intensive
            # " && razers3 --percent-identity 90 --max-hits 1 --distance-range 0 --output {hla_bam} {HLA_REF} {RNA_TUMOR_FQ1} {RNA_TUMOR_FQ2}"
            " && samtools fastq {hla_bam} -1 {hla_fq_r1} -2 {hla_fq_r2} -s {hla_fq_se}"
            " && rm -r {RES}/hla_typing/optitype_out/ || true"
            " && mkdir -p {RES}/hla_typing/optitype_out")
        if RNA_TUMOR_ISPE:
            shell("OptiTypePipeline.py -i {hla_fq_r1} {hla_fq_r2} --rna -o {RES}/hla_typing/optitype_out/ > {output.out}.OptiType.stdout")
        else:
            shell("OptiTypePipeline.py -i {hla_fq_se} --rna -o {RES}/hla_typing/optitype_out/ > {output.out}.OptiType.stdout")
        shell("cp {RES}/hla_typing/optitype_out/*/*_result.tsv {output.out}")

#kallisto_cdna = "/mnt/d/code/neohunter/NeoHunter/Homo_sapiens.GRCh37.cdna.all.fa"

kallisto_out = F"{RES}/rna_quantification/{PREFIX}_kallisto_out"
outf_rna_quantification = F"{RES}/rna_quantification/abundance.tsv"
rule rna_quantification:
    output:
        out = outf_rna_quantification
    run:
        if RNA_TUMOR_ISPE:
            shell("kallisto quant -i {CTAT}/ref_annot.cdna.fa.kallisto-idx -b 100 -o {kallisto_out} {RNA_TUMOR_FQ1} {RNA_TUMOR_FQ2}")
        else:
            shell("kallisto quant -i {CTAT}/ref_annot.cdna.fa.kallisto-idx -b 100 -o {kallisto_out} --single -l 200 -s 30 {RNA_TUMOR_FQ1}")
        shell("cp {kallisto_out}/abundance.tsv {output.out}")

starfusion_out = F"{RES}/alteration_detection/starfusion_out"
starfusion_bam = F"{starfusion_out}/Aligned.out.bam"
starfusion_res = F"{starfusion_out}/star-fusion.fusion_predictions.abridged.coding_effect.tsv"
starfusion_sjo = F"{starfusion_out}/SJ.out.tab"
starfusion_params = F" --genome_lib_dir {CTAT} --examine_coding_effect --output_dir {starfusion_out} --min_FFPM 0.1 "
rule rna_fusion_detection:
    output:
        outbam = starfusion_bam,
        outres = starfusion_res,
        outsjo = starfusion_sjo,
    run: # {script_basedir}/../STAR-Fusion-v1.11.0/
        if RNA_TUMOR_ISPE: #  --outFileNamePrefix "+rna_alignment_path + " --outTmpDir /tmp/STAR-2.7.8a.tmp
            shell("STAR-Fusion {starfusion_params} --CPU {workflow.cores} --left_fq {RNA_TUMOR_FQ1} --right_fq {RNA_TUMOR_FQ2}")
        else:
            shell("STAR-Fusion {starfusion_params} --CPU {workflow.cores} --left_fq {RNA_TUMOR_FQ1}")

fusion_neopeptide_faa = F"{neopeptide_dir}/{PREFIX}_fusion.fasta"
rule rna_fusion_neopeptide_generation:
    input:
        starfusion_res, outf_rna_quantification
    output:
        fusion_neopeptide_faa, fusion_info_file
    shell:
        "python {script_basedir}/parse_star_fusion.py -i {starfusion_res}"
        " -e {outf_rna_quantification} -o {starfusion_out} -p {PREFIX} -t 1.0"
        " && cp {starfusion_out}/{PREFIX}_fusion.fasta {neopeptide_dir}/{PREFIX}_fusion.fasta"
        " && cp {starfusion_res} {fusion_info_file}"
        
rna_tumor_bam = F"{alignment_dir}/{PREFIX}_RNA_tumor.bam"
rna_t_spl_bam = F"{alignment_dir}/{PREFIX}_RNA_t_spl.bam" # tumor splicing
dna_tumor_bam = F"{alignment_dir}/{PREFIX}_DNA_tumor.bam"
dna_normal_bam = F"{alignment_dir}/{PREFIX}_DNA_normal.bam"

rna_tumor_bai = F"{alignment_dir}/{PREFIX}_RNA_tumor.bam.bai"
rna_t_spl_bai = F"{alignment_dir}/{PREFIX}_RNA_t_spl.bam.bai"
dna_tumor_bai = F"{alignment_dir}/{PREFIX}_DNA_tumor.bam.bai"
dna_normal_bai = F"{alignment_dir}/{PREFIX}_DNA_normal.bam.bai"

bam2fqs = {
    rna_tumor_bam : (RNA_TUMOR_FQ1, RNA_TUMOR_FQ2, RNA_TUMOR_ISPE),
    dna_tumor_bam : (DNA_TUMOR_FQ1, DNA_TUMOR_FQ2, DNA_TUMOR_ISPE),
    dna_normal_bam : (DNA_NORMAL_FQ1, DNA_NORMAL_FQ2, DNA_NORMAL_ISPE)
}

HIGH_DP=1000*1000
# rna_tumor_depth = F"{alignment_dir}/{PREFIX}_rna_tumor_F0xD04_depth.tsv.gz"
rna_tumor_depth = F"{alignment_dir}/{PREFIX}_rna_tumor_F0xD04_depth.vcf.gz"
rna_tumor_depth_summary = F"{alignment_dir}/{PREFIX}_rna_tumor_F0xD04_depth_summary.tsv.gz"
rule rna_preprocess:
    input:
        starfusion_bam
    output:
        outbam = rna_tumor_bam,
        outbai = rna_tumor_bai,
        outdepth = rna_tumor_depth,
        outsummary = rna_tumor_depth_summary,
    shell:
        "rm {output.outbam}.tmp.*.bam || true " 
        " && samtools fixmate -@ {workflow.cores} -m {starfusion_bam} - "
        " | samtools sort -@ {workflow.cores} -o - - "
        " | samtools markdup -@ {workflow.cores} - {rna_tumor_bam} "
        " && samtools index -@ {workflow.cores} {rna_tumor_bam}"
        " && samtools view -hu -@ {workflow.cores} -F 0xD04 {rna_tumor_bam} "
        #" | samtools depth -d {HIGH_DP} -s -b {CTAT}/ref_annot.gtf.mini.sortu.bed - "
        #" | gzip --fast > {rna_tumor_depth}"
        " | bcftools mpileup --threads {workflow.cores} -a DP,AD -d {HIGH_DP} -f {REF} -q 0 -Q 0 -T {CTAT}/ref_annot.gtf.mini.sortu.bed - -o {rna_tumor_depth} "
        " && bcftools index --threads {workflow.cores} -ft {rna_tumor_depth} "
        " && cat {CTAT}/ref_annot.gtf.mini.sortu.bed | awk '{{ i += 1; s += $3-$2 }} END {{ print \"exome_total_bases\t\" s; }}' > {rna_tumor_depth_summary}"
        # " && zcat {rna_tumor_depth} | awk '{ i += 1 ; s += $3 } END { print \"exome_total_depth\t\" s; }' >> {rna_tumor_depth_summary}"
        " && bcftools query -f '%DP\n' {rna_tumor_depth} | awk '{{ i += 1 ; s += $1 }} END {{ print \"exome_total_depth\t\" s; }}' >> {rna_tumor_depth_summary}"
   
asneo_out = F"{RES}/splicing/{PREFIX}_rna_tumor_splicing_asneo_out"
asneo_sjo = F"{asneo_out}/SJ.out.tab"
splicing_neopeptide_faa=F"{neopeptide_dir}/{PREFIX}_splicing.fasta"
rule rna_splicing_alignment:
    output: rna_t_spl_bam, rna_t_spl_bai, asneo_sjo 
    shell: # same as in PMC7425491 except for --sjdbOverhang 100
        "STAR --genomeDir {REF}.star.idx --readFilesIn {RNA_TUMOR_FQ1} {RNA_TUMOR_FQ2} --runThreadN {workflow.cores} "
        " –-outFilterMultimapScoreRange 1 --outFilterMultimapNmax 20 --outFilterMismatchNmax 10 --alignIntronMax 500000 –alignMatesGapMax 1000000 "
        " --sjdbScore 2 --alignSJDBoverhangMin 1 --genomeLoad NoSharedMemory --outFilterMatchNminOverLread 0.33 --outFilterScoreMinOverLread 0.33 "
        " --sjdbOverhang 150 --outSAMstrandField intronMotif –sjdbGTFfile {asneo_gtf} --outFileNamePrefix {asneo_out}/ --readFilesCommand 'gunzip -c' " 
        " --outSAMtype BAM Unsorted "
        " && samtools fixmate -@ {workflow.cores} -m {asneo_out}/Aligned.out.bam - "
        " | samtools sort -@ {workflow.cores} -o - -"
        " | samtools markdup -@ {workflow.cores} - {rna_t_spl_bam}"
        " && samtools index -@ {workflow.cores} {rna_t_spl_bam}"
rule rna_splicing_neopeptide_generation:
    input: rna_quant=outf_rna_quantification, sj=asneo_sjo # starfusion_sjo,
    output: splicing_neopeptide_faa
    threads: 1
    shell:
        "mkdir -p {info_dir} "
        " && python {script_basedir}/software/ASNEO/neoheadhunter_ASNEO.py -j {input.sj} -g {asneo_ref} -o {asneo_out} -l 8,9,10,11 -p {PREFIX} -t 1.0 "
        " -e {outf_rna_quantification}"
        " && cat {asneo_out}/{PREFIX}_splicing_* > {neopeptide_dir}/{PREFIX}_splicing.fasta"

rule dna_alignment_tumor:
    output: dna_tumor_bam, dna_tumor_bai
    shell:
        "rm {dna_tumor_bam}.tmp.*.bam || true"
        " && bwa mem -t {workflow.cores} {REF} {DNA_TUMOR_FQ1} {DNA_TUMOR_FQ2} "
        " | samtools fixmate -@ {workflow.cores} -m - -"
        " | samtools sort -@ {workflow.cores} -o - -"
        " | samtools markdup -@ {workflow.cores} - {dna_tumor_bam}"
        " && samtools index -@ {workflow.cores} {dna_tumor_bam}"

rule dna_alignment_normal:
    output: dna_normal_bam, dna_normal_bai
    shell:
        "rm {dna_normal_bam}.tmp.*.bam || true"
        " && bwa mem -t {workflow.cores} {REF} {DNA_NORMAL_FQ1} {DNA_NORMAL_FQ2} "
        " | samtools fixmate -@ {workflow.cores} -m - -"
        " | samtools sort -@ {workflow.cores} -o - -"
        " | samtools markdup -@ {workflow.cores} - {dna_normal_bam}"
        " && samtools index -@ {workflow.cores} {dna_normal_bam}"

dna_vcf=F"{snvindel_dir}/{PREFIX}_DNA_tumor_DNA_normal.vcf"
rule snvindel_detection_with_DNA_tumor:
    input: tbam=dna_tumor_bam, tbai=dna_tumor_bai, nbam=dna_normal_bam, nbai=dna_normal_bai,
    output: dna_vcf,
        vcf1 = F"{snvindel_dir}/{PREFIX}_DNA_tumor_DNA_normal.uvcTN.vcf.gz",
        vcf2 = F"{snvindel_dir}/{PREFIX}_DNA_tumor_DNA_normal.uvcTN-filter.vcf.gz",
        vcf3 = F"{snvindel_dir}/{PREFIX}_DNA_tumor_DNA_normal.uvcTN-delins.merged-simple-delins.vcf.gz",        
    shell:
        "uvcTN.sh {REF} {dna_tumor_bam} {dna_normal_bam} {output.vcf1} {PREFIX}_DNA_tumor,{PREFIX}_DNA_normal "
            " 1> {output.vcf1}.stdout.log 2> {output.vcf1}.stderr.log"
        " && bcftools view {output.vcf1} -Oz -o {output.vcf2} "
            " -i \"(QUAL >= 63) && (tAD[1] >= {tumor_depth}) && (tAD[1] >= (tAD[0] + tAD[1]) * {tumor_vaf}) && (nAD[1] <= (nAD[0] + nAD[1]) * {normal_vaf})\""
        " && bash uvcvcf-raw2delins-all.sh {REF} {output.vcf2} {snvindel_dir}/{PREFIX}_DNA_tumor_DNA_normal.uvcTN-delins"
        " && bcftools view {output.vcf3} -Ov -o {dna_vcf}"

rna_vcf=F"{snvindel_dir}/{PREFIX}_RNA_tumor_DNA_normal.vcf"
rule snvindel_detection_with_RNA_tumor:
    input: tbam=rna_tumor_bam, tbai=rna_tumor_bai, nbam=dna_normal_bam, nbai=dna_normal_bai
    output: rna_vcf,
        vcf1 = F"{snvindel_dir}/{PREFIX}_RNA_tumor_DNA_normal.uvcTN.vcf.gz",
        vcf2 = F"{snvindel_dir}/{PREFIX}_RNA_tumor_DNA_normal.uvcTN-filter.vcf.gz",
        vcf3 = F"{snvindel_dir}/{PREFIX}_RNA_tumor_DNA_normal.uvcTN-delins.merged-simple-delins.vcf.gz",
    shell:
        "uvcTN.sh {REF} {rna_tumor_bam} {dna_normal_bam} {output.vcf1} {PREFIX}_RNA_tumor,{PREFIX}_DNA_normal "
            " 1> {output.vcf1}.stdout.log 2> {output.vcf1}.stderr.log"
        " && bcftools view {output.vcf1} -Oz -o {output.vcf2} "
            " -i \"(QUAL >= 63) && (tAD[1] >= {tumor_depth}) && (tAD[1] >= (tAD[0] + tAD[1]) * {tumor_vaf}) && (nAD[1] <= (nAD[0] + nAD[1]) * {normal_vaf})\""
        " && bash uvcvcf-raw2delins-all.sh {REF} {output.vcf2} {snvindel_dir}/{PREFIX}_RNA_tumor_DNA_normal.uvcTN-delins"
        " && bcftools view {output.vcf3} -Ov -o {rna_vcf}"

dna_variant_effect = F"{snvindel_dir}/{PREFIX}_DNA_tumor_DNA_normal.variant_effect.tsv"
rule snvindel_effect_prediction:
    input: dna_vcf
    output: dna_variant_effect
    shell: """{vep_exe} --no_stats --ccds --uniprot --hgvs --symbol --numbers --domains --gene_phenotype --canonical --protein --biotype --tsl --variant_class \
        --check_existing --total_length --allele_number --no_escape --xref_refseq --flag_pick_allele --offline --pubmed --af --af_1kg --af_esp --af_gnomad \
        --regulatory --force_overwrite --assembly GRCh37 --buffer_size 5000 --failed 1 --format vcf --pick_order canonical,tsl,biotype,rank,ccds,length \
        --polyphen b --shift_hgvs 1 --sift b --species homo_sapiens \
        --dir {vep_cache} --fasta {REF} --fork {workflow.cores} --input_file {dna_vcf} --output_file {dna_variant_effect}"""

snvindel_neopeptide_faa = F"{neopeptide_dir}/{PREFIX}_snv_indel.fasta"
snvindel_wt_peptide_faa = F"{neopeptide_dir}/{PREFIX}_snv_indel_wt.fasta"
rule snvindel_neopeptide_generation:
    input: dna_variant_effect,
    output: snvindel_neopeptide_faa, snvindel_wt_peptide_faa, snvindel_info_file
    shell: """python {script_basedir}/annotation2fasta.py -i {dna_variant_effect} -o {neopeptide_dir} -p {ref_pep_fa} \
        -r {REF} -s VEP -e {outf_rna_quantification} -t {workflow.cores} -P {PREFIX}
        cp {neopeptide_dir}/{PREFIX}_tmp_fasta/{PREFIX}_snv_indel_wt.fasta {snvindel_wt_peptide_faa}
        cp {dna_variant_effect} {snvindel_info_file}"""
   
def retrieve_hla_alleles():
    ret = []
    with open(F'{hla_out}') as file:
        reader = csv.reader(file, delimiter="\t")
        for line in reader:
            if line[0] == "": continue
            for i in range(1,7,1): ret.append("HLA-" + line[i].replace("*",""))
    return ret

def run_netMHCpan(args):
    hla_str, infaa = args
    return call_with_infolog(F'{netmhcpan_cmd} -f {infaa} -a {hla_str} -l 8,9,10,11 -BA > {infaa}.netMHCpan-result')

def peptide_to_pmhc_binding_affinity(infaa, outtsv, hla_strs, ncores = 6):
    call_with_infolog(F"rm {outtsv}.tmpdir/* || true && mkdir -p {outtsv}.tmpdir/")
    call_with_infolog(F"split -l 20 {infaa} {outtsv}.tmpdir/SPLITTED.")
    # args = [(hla_str, F"{outtsv}.tmpdir/{faafile}") for hla_str in hla_strs for faafile in os.listdir(F"{outtsv}.tmpdir/") if faafile.startswith("SPLITTED.")]
    cmds = [F'{netmhcpan_cmd} -f {outtsv}.tmpdir/{faafile} -a {hla_str} -l 8,9,10,11 -BA > {outtsv}.tmpdir/{faafile}.{hla_str}.netMHCpan-result'
            for hla_str in hla_strs for faafile in os.listdir(F"{outtsv}.tmpdir/") if faafile.startswith("SPLITTED.")]
    with open(F'{outtsv}.tmpdir/tmp.sh', 'w') as shfile:
        for cmd in cmds: shfile.write(cmd + '\n')
    # Each netmhcpan process uses much less than 100% CPU, so we can spawn many more processes
    call_with_infolog(F'cat {outtsv}.tmpdir/tmp.sh | parallel -j {4*ncores}')
    #multiprocessing.Pool(int(ncores)).map(run_netMHCpan, args)
    call_with_infolog(F"cat {outtsv}.tmpdir/SPLITTED.*.netMHCpan-result > {outtsv}")
    
snvindel_pmhc_mt_txt = F"{pmhc_dir}/{PREFIX}_snvindel_netmhc.txt"
snvindel_pmhc_wt_txt = F"{pmhc_dir}/{PREFIX}_snvindel_netmhc_wt.txt"
fusion_pmhc_mt_txt   = F"{pmhc_dir}/{PREFIX}_fusion_netmhc.txt"
splicing_pmhc_mt_txt = F"{pmhc_dir}/{PREFIX}_splicing_netmhc.txt"

all_vars_pmhc_mt_tsv = F"{pmhc_dir}/{PREFIX}_bindaff_raw.tsv"
snvindel_pmhc_wt_tsv = F"{pmhc_dir}/{PREFIX}_snv_indel_bindaff_wt.tsv"

all_vars_neopeptide_faa = F"{pmhc_dir}/{PREFIX}_alteration_derived_pep.fasta"

rule pmhc_binding_affinity_prediction:
    input: snvindel_neopeptide_faa, snvindel_wt_peptide_faa, fusion_neopeptide_faa, splicing_neopeptide_faa, hla_out
    output: snvindel_pmhc_mt_txt, snvindel_pmhc_wt_txt, fusion_pmhc_mt_txt, splicing_pmhc_mt_txt
    run:
        peptide_to_pmhc_binding_affinity(snvindel_neopeptide_faa, snvindel_pmhc_mt_txt, retrieve_hla_alleles(), workflow.cores)
        peptide_to_pmhc_binding_affinity(snvindel_wt_peptide_faa, snvindel_pmhc_wt_txt, retrieve_hla_alleles(), workflow.cores)
        peptide_to_pmhc_binding_affinity(  fusion_neopeptide_faa,   fusion_pmhc_mt_txt, retrieve_hla_alleles(), workflow.cores)
        logging.info('Almost finished running pmhc_binding_affinity_prediction')
        peptide_to_pmhc_binding_affinity(splicing_neopeptide_faa, splicing_pmhc_mt_txt, retrieve_hla_alleles(), workflow.cores)
        logging.info('Finished running pmhc_binding_affinity_prediction')

print(F'snvindel_pmhc_mt_txt = {snvindel_pmhc_mt_txt}')

wt_bindaff_filtered_tsv = F"{pmhc_dir}/tmp_identity/{PREFIX}_bindaff_filtered.tsv"
mt_bindaff_filtered_tsv = F"{pmhc_dir}/{PREFIX}_bindaff_filtered.tsv"

print(F'snvindel_pmhc_XX_tsv = {wt_bindaff_filtered_tsv} and {mt_bindaff_filtered_tsv}')

rule pmhc_binding_affinity_filter:
    input: snvindel_pmhc_mt_txt, snvindel_pmhc_wt_txt, fusion_pmhc_mt_txt, splicing_pmhc_mt_txt
    output: wt_bindaff_filtered_tsv, mt_bindaff_filtered_tsv
    #, "{all_vars_neopeptide_faa}" # by parse_netMHC.py
    shell: F"""
        cat {snvindel_pmhc_mt_txt} {fusion_pmhc_mt_txt} {splicing_pmhc_mt_txt} > {all_vars_pmhc_mt_tsv} || true
        cp {snvindel_pmhc_wt_txt} {snvindel_pmhc_wt_tsv}
        cat {snvindel_neopeptide_faa} {fusion_neopeptide_faa} {splicing_neopeptide_faa} > {all_vars_neopeptide_faa}
        python {script_basedir}/parse_netMHC.py -i {pmhc_dir} -g {all_vars_neopeptide_faa} -b {binding_affinity_thres} -l N/A -p {PREFIX} -o {pmhc_dir}"""

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse
def uri_to_user_address_port_path(uri):
    if uri.startswith("ssh://"):
        parsed_url = urlparse(uri)
        addressport = parsed_url.netloc.split(':')
        assert len(addressport) <= 2
        if len(addressport) == 2:
            complete_address, port = addressport
        else:
            complete_address, port = (addressport[0], 22)
        useraddress = complete_address.split('@')
        assert len(useraddress) <= 2
        if len(useraddress) == 2:
            user, address = useraddress
        else:
            user, address = (parsed_url.username, useraddress[0])
        return (user, address, port, parsed_url.path)
    return (None, None, None, uri)

def run_netMHCstabpan(bindstab_filter_py, inputfile = F"{pmhc_dir}/{PREFIX}_bindaff_filtered.tsv", outdir = pmhc_dir):
    user, address, port, path = uri_to_user_address_port_path(netmhcstabpan_path)
    if netmhcstabpan_path == path:
        run_calculation = F"python {bindstab_filter_py} -i {inputfile} -o {outdir} -n {path} -b {binding_stability_thres} -p {PREFIX}"
        call_with_infolog(run_calculation)
    else:
        outputfile1 = F"{outdir}/{PREFIX}_bindstab_raw.csv" # pmhc_binding_prediction_folder+"/"+prefix+"_bindstab_raw.csv"
        outputfile2 = F"{outdir}/{PREFIX}_candidate_pmhc.csv" # pmhc_binding_prediction_folder+"/"+prefix+"_candidate_pmhc.csv"
        remote_mkdir = F" sshpass -p \"$NeohunterRemotePassword\" ssh -p {port} {user}@{address} mkdir -p /tmp/{outdir}/"
        remote_send = F" sshpass -p \"$NeohunterRemotePassword\" scp -P {port} {bindstab_filter_py} {inputfile} {user}@{address}:/tmp/{outdir}/"
        remote_main_cmd = F"python /tmp/{outdir}/bindstab_filter.py -i /tmp/{inputfile} -o /tmp/{outdir} -n {path} -b {binding_stability_thres} -p {PREFIX}"
        remote_exe = F" sshpass -p \"$NeohunterRemotePassword\" ssh -p {port} {user}@{address} {remote_main_cmd}"
        remote_receive1 = F" sshpass -p \"$NeohunterRemotePassword\" scp -P {port} {user}@{address}:/tmp/{outputfile1} {outdir}"
        remote_receive2 = F" sshpass -p \"$NeohunterRemotePassword\" scp -P {port} {user}@{address}:/tmp/{outputfile2} {outdir}"
        call_with_infolog(remote_mkdir)
        call_with_infolog(remote_send)
        call_with_infolog(remote_exe)
        call_with_infolog(remote_receive1)
        call_with_infolog(remote_receive2)

mt_bindstab_raw_tsv = F"{pmhc_dir}/{PREFIX}_bindstab_raw.csv"
mt_bindstab_filtered_tsv = F"{pmhc_dir}/{PREFIX}_candidate_pmhc.csv"
rule pmhc_binding_stability_filter:
    input: mt_bindaff_filtered_tsv
    output: mt_bindstab_raw_tsv, mt_bindstab_filtered_tsv
    run: 
        bindstab_filter_py = F"{script_basedir}/bindstab_filter.py"
        run_netMHCstabpan(bindstab_filter_py, F"{mt_bindaff_filtered_tsv}", F"{pmhc_dir}")

iedb_path = '/mnt/d/code/neohunter/NeoHunter/database/iedb.fasta'
prioritization_params = ''
neoheadhunter_prioritization_tsv = F"{prioritization_dir}/{PREFIX}_neoantigen_rank_neoheadhunter.tsv"
print(F'neoheadhunter_prioritization_tsv = {neoheadhunter_prioritization_tsv} (from {prioritization_dir})')
rule prioritization_with_all_tcr:
    input: iedb_path, wt_bindaff_filtered_tsv, mt_bindaff_filtered_tsv, mt_bindstab_filtered_tsv, rna_vcf, rna_tumor_depth_summary, 
        snvindel_info_file, fusion_info_file
    output: neoheadhunter_prioritization_tsv
    run: 
        call_with_infolog(F"bcftools view {rna_vcf} -Oz -o {rna_vcf}.gz && bcftools index -ft {rna_vcf}.gz ")
        call_with_infolog(F"python {script_basedir}/neoheadhunter_prioritization.py -i {pmhc_dir} -I {iedb_path} -o {prioritization_dir} "
            F" -n {netmhcpan_path} -a {agretopicity_recognition_thres} -f {foreignness_recognition_thres} -t {alteration_type} -p {PREFIX} "
            F" -T {tumor_abundance_thres} --rna_vcf={rna_vcf}.gz --rna_depth={rna_tumor_depth_summary} " # --var_effect={dna_variant_effect} "
            F" {prioritization_params.replace('_', '-')}")

#rule prioritization_with_each_tcr:
    