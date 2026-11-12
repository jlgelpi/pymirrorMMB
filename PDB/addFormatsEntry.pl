#!/usr/bin/perl
#
# @File addCifOnly.pl.pl
# @Author gelpi
# @Created 28-jun-2017 15:58:52
#
# Mark entries only available as cif
#
use lib $ENV{'MIRRORSCR'}."/lib";
use MMBData::Log;
use MMBData::MongoDBConnect;
use strict;
use Data::Dumper;
use LWP::Simple;

my $entriesCol = MongoDBConnect::connectCol('127.0.0.1','FlexPortal',0,1,'PDB_Entry');
my $strucFilesCol = MongoDBConnect::connectCol('127.0.0.1','PDB_DataFiles',1,1,'fs.files');
my $IDS={};
my $ids_c = $strucFilesCol->find()->fields({'filename'=>1});
while (my $d=$ids_c->next()) {
    my $fn = $d->{'filename'};
    if ($fn =~ /^pdb(....)/) {
        push @{$IDS->{$1}},'pdb';
    } elsif ( $fn =~ /(....)\.cif.gz/) {
        push @{$IDS->{$1}},'mmCif';
    } else  {
        $fn =~ /(....)\.xml.gz/;
        push @{$IDS->{$1}},'xml';
    } 
}
foreach my $k (keys %{$IDS}) {
    my $id = $k;
    $id =~ tr/a-z/A-Z/;
    $entriesCol->update ({'_id'=>$id},{'$set' => {'formats'=> $IDS->{$k}}});
}


