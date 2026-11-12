#!/usr/bin/perl -w

# Generating a PNG image of a PDB Structure using VMD.

use strict;

my $long=@ARGV;
if ($long != 3){
    print "Usage: perl $0 <pdbCode> <pdbFile> <outImage>\n";
    exit(0);
}

my ($idCode,$fpdb,$fout)=@ARGV;

my $VMDDIR = "/home/gelpi/mirrorMMB/soft/vmd";
my $VMDBIN = "$VMDDIR/vmd";
my $STRIDEBIN = "$VMDDIR/bin/stride";

my $ftmp = "$idCode.protein.tga";
my $projDir = ".";
print "$idCode\n";
if ($fpdb =~ /gz$/){
	my $cmd = "zcat $fpdb > $idCode.pdb";
	`$cmd`;
	$fpdb = "$idCode.pdb";
}

my $vmdScriptFile = $projDir."/$idCode.vmdScript";
open VMD, ">$vmdScriptFile";
print VMD "mol load pdb $fpdb\n";
my $vmdScript = << 'EOF';
                display projection orthographic
                color Display Background white
                axes location off
                display nearclip set 0
                display height 4
                package require Orient
                namespace import Orient::orient
                set sel [atomselect top "protein or nucleic"]
                set I [draw principalaxes $sel]
                set A [orient $sel [lindex $I 2] {1 0 0}]
                $sel move $A
                set I [draw principalaxes $sel]
                set A [orient $sel [lindex $I 1] {0 1 0}]
                $sel move $A
                graphics top delete all
                mol delrep 0 0
                mol color structure
                mol material BrushedMetal
                mol representation newCartoon 0.2 20 5
                mol addrep top
                mol color colorid 4
                mol material BrushedMetal
                mol selection (within 5 of resname \"CY\.\") and (resname \"CY\.\")  and mass > 2
                mol representation Licorice 0.3 20 20
                mol addrep top
                mol representation NewRibbons 0.300000 6.000000 3.000000 0
                mol color Element
                mol selection {nucleic}
                mol addrep top
                mol representation Tube 0.300000 6.000000
                mol selection {nucleic}
                mol addrep top
EOF
print VMD $vmdScript;
print VMD "render TachyonInternal $ftmp\n";
print VMD "quit\n";
close VMD;

#my $vmdQueueFile = $projDir."/q$idCode.vmdScript";
#open VMDQ,">$vmdQueueFile";
#print VMDQ "\#\!/bin/bash\n";
#print VMDQ "\#\$ -q www.q\@s002\n";
#print VMDQ "\#\$ -N q$idCode\n";
#print VMDQ "\#\$ -cwd\n\n";
#        fprintf ($fq0, "%s\n", "export VMDDIR=".VMDDIR);
#        fprintf ($fq0, "%s\n", "export STRIDE_BIN=".STRIDEBIN."\n");
#print VMDQ "hostname\n";
#print VMDQ "whoami\n";
#print VMDQ "pwd\n";
system ("$VMDBIN -dispdev text -size 300 300 -e $vmdScriptFile");
system ("tgatoppm $ftmp | pnmcrop -white | pnmtopng -transparent white > $fout");
unlink ($vmdScriptFile);
unlink ($ftmp);
unlink ("$idCode.pdb");
#close VMDQ;

# Queueing Process
#exec("csh $vmdQueueFile");

