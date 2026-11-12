#!/usr/bin/perl -w
# Generating a PNG image of ALL the PDB Structures using VMD.
use lib $ENV{'MIRRORSCR'}."/lib";
#use MMBData::Log;
use MMBData::MongoDBConnect;
use strict;

my $tmpDir = "/home/ubuntu/mirrorMMB/tmpData/VMD";
my $genVMD ="/home/ubuntu/mirrorMMB/PDBScripts/genVMDpict.pl";

my $entriesCol = MongoDBConnect::connect('127.0.0.1', 'FlexPortal',1,'PDB_Entry')->{'PDB_Entry'};
print $entriesCol;

my @codes = $entriesCol->find (
    {'supersby' =>
        {'$exists' => 0}
    },
    {'_id'=> 1}
)->all(); 
chdir $tmpDir;
`mongofiles -u gelpi -p jl12gb96jl87 --authenticationDatabase admin -d PDB_Picts list > PDB_Picts.list`;
my %picts;
open LIST, 'PDB_Picts.list';
while (<LIST>) {
    chomp;
    my ($f,$s) = split ' ';
    if ($s) {
        $picts{$f} = 1;
    }
}
foreach my $pdbdata (@codes) {
    my $idCode = $pdbdata->{'_id'};
    my $idCodelc = $idCode;
    $idCodelc =~ tr/A-Z/a-z/;
    my $pictFn = "$idCode.png";
    print "-".$idCodelc."-\n";
    if (!$picts{$pictFn}) {
    	print `mongofiles -u gelpi -p jl12gb96jl87 --authenticationDatabase admin -d PDB_DataFiles get pdb$idCodelc.ent.gz`;
	print `perl $genVMD $idCode pdb$idCodelc.ent.gz $idCode.png`;
	print `mongofiles -u dataLoader -p mdbwany2015 --authenticationDatabase admin -d PDB_Picts -r put $idCode.png`;
	unlink "$idCode.png";
	unlink "pdb$idCodelc.ent.gz";
	unlink "*vmd*";
    }
}
