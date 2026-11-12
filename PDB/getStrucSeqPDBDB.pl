#!/usr/bin/perl
# matching sequence from pdb_seqres and structure: Output Diff and aligned Fasta MongoDB version
use MongoDB;
use MongoDB::OID;
use strict;
use Data::Dumper;
use LWP::Simple;
use JSON;
#
my $APIPrefix = "https://mdb-login.bsc.es/api/pdb";
my $MINLENGTH=5;
my $oneletter={
'ALA'=>'A', 'CYS'=>'C', 'ASP'=>'D', 'GLU'=>'E',
'PHE'=>'F', 'GLY'=>'G', 'HIS'=>'H', 'ILE'=>'I',
'LYS'=>'K', 'LEU'=>'L', 'MET'=>'M', 'ASN'=>'N',
'PRO'=>'P', 'GLN'=>'Q', 'ARG'=>'R', 'SER'=>'S',
'THR'=>'T', 'VAL'=>'V', 'TRP'=>'W', 'TYR'=>'Y',
'A' => 'A', 'C' => 'C', 'G' => 'G', 'T' => 'T',
'U' => 'U', 'DA' => 'A', 'DC' => 'C', 'DG' => 'G',
'DT' => 'T'
};
my $upd=0;
if ($ARGV[0] eq "--upd") {
	$upd=1;
	shift;
}
my $ini= shift;
my $ch='';
#
my $mconn = MongoDB::MongoClient->new(host => '127.0.0.1', username => 'gelpi', password=>'XXXXXXXXXX');
#$mconn->authenticate('admin','dataLoader','mdbwany2015');
my $db = $mconn->get_database( 'FlexPortal' );
my $entriesCol = $db->get_collection('PDB_Entry');
my $chainsCol = $db->get_collection('chain');
my $sequencesCol = $db->get_collection('sequences');
#
#
my $p=0;
#my $webData = get("$APIPrefix?fields=ids&noheaders") or die "Cannot connect to $APIPrefix";
my $webData = `curl -s "$APIPrefix?fields=ids&noheaders"`;
my @pdbIds = sort split "\n", $webData;
#print get($APIPrefix.'?fields=ids&noheaders');
#my $c = $entriesCol->find({},{'_id' => 1})->sort({'_id'=>1});
#while (my $pdbData = $c->next()) {
foreach my $id (@pdbIds) {
#    my $id = $pdbData->{'_id'};
    $id =~ s/\t//g;
    print "-$id-$ini-$p\n";
    if ($p || !$ini || ($id eq $ini)) {$p=1}
    next if !$p;
    if ($upd) {
		my $webData = `curl -s "$APIPrefix/$id/entry/chains/0/PDBSequence"`;
		#my $pp = decode_json get("$APIPrefix/$id/entry/chains/0/PDBSequence/sequence");
		print $webData;
		my $pp = decode_json $webData;
		next if ($pp->{'_id'});
	}
    my $chains ={};
    my $webData = `curl -s "$APIPrefix/$id/?group=ATOM&filter=:.CA,O5%27/1"`;
	#my @pdbStruc = split "\n", get("$APIPrefix/$id/?group=ATOM&filter=:.CA,O5%27/1");
	my @pdbStruc = split "\n", $webData;
    foreach my $line (@pdbStruc) {
	next if ($line !~ /^ATOM/);
# Alternate confs
        my $altId = substr($line,16,1);
        next if ($altId !~ /[ A]/);
	my ($resid, $chid, $resnum) = (substr($line,17,4), substr($line,21,2), substr($line,23,4));
	$chid =~ s/ //g;
	next if ($ch && ($ch ne $chid));
	$resid =~ s/ //g;
	if (!$chains->{$chid}) {
		$chains->{$chid}->{'ini'} = $resnum;
		$chains->{$chid}->{'fragments'}->[0]->{'ini'} = $resnum+0;
		$chains->{$chid}->{'fragments'}->[0]->{'fin'} = $resnum+0;
		$chains->{$chid}->{'fragments'}->[0]->{'seq'} = $oneletter->{$resid};
		$chains->{$chid}->{'nfrag'}= 1;
	} elsif (($resnum-1) > $chains->{$chid}->{'fragments'}->[$chains->{$chid}->{'nfrag'}-1]->{'fin'}) { # Gap obrim fragment nou
		$chains->{$chid}->{'nfrag'}++;
		$chains->{$chid}->{'fragments'}->[$chains->{$chid}->{'nfrag'}-1]->{'ini'} = $resnum+0;
		$chains->{$chid}->{'fragments'}->[$chains->{$chid}->{'nfrag'}-1]->{'fin'} = $resnum+0;
		$chains->{$chid}->{'fragments'}->[$chains->{$chid}->{'nfrag'}-1]->{'seq'} = $oneletter->{$resid};
	} else {
		$chains->{$chid}->{'fragments'}->[$chains->{$chid}->{'nfrag'}-1]->{'fin'} = $resnum+0;
		$chains->{$chid}->{'fragments'}->[$chains->{$chid}->{'nfrag'}-1]->{'seq'} .= $oneletter->{$resid};
        }
    }
    foreach my $chid (sort keys(%$chains)){
	my @frags;
	my @seqs;
        my $sq ='';
        my $lfin=0;
	foreach my $n (0 .. $chains->{$chid}->{'nfrag'}-1) {
                $sq .='-' x ($chains->{$chid}->{'fragments'}->[$n]->{'ini'}-$lfin-1).$chains->{$chid}->{'fragments'}->[$n]->{'seq'};
		push @frags, "$chains->{$chid}->{'fragments'}->[$n]->{'ini'}-$chains->{$chid}->{'fragments'}->[$n]->{'fin'}";
		$lfin = $chains->{$chid}->{'fragments'}->[$n]->{'fin'};
	}
        my $strucSq = {
            'fragments' => [@frags],
            'sequence' => $sq
        };
    print ">$id $chid ". join (',',@{$strucSq->{'fragments'}})."\n".$strucSq->{'sequence'}."\n";
    $sequencesCol->update_one (
        {'_id' => $id."_$chid"},
        {'$set' => {'PDBSequence' => $strucSq}}
    );
	print "ok\n";
    }
}
