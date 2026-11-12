#!/usr/bin/perl
use strict;
use MongoDB;
use MongoDB::OID;
use Data::Dumper;
my $mconn= MongoDB::MongoClient->new(host=>'mmb.pcb.ub.es');
$mconn->authenticate("admin","dataLoader","mdbwany2015");
my $db = $mconn->get_database("FlexPortal");
my $PDBCol = $db->get_collection("PDB_Entry");
#
print "MoDEL\n";
#while (<>) {
#	chomp;
##	tr/a-z/A-Z/;
#	s/ *//g;
#	print "-$_-\n";;
#        $PDBCol->update({'_id'=>$_},{'$addToSet'=>{'MDDBS' => 'MoDEL'}});
#}
print "BNS\n";
my $bnsdb = $mconn->get_database("NUCMDANAL");
my $simDataCol = $bnsdb->get_collection("simData");
my $c = $simDataCol->find({'PDB'=>{'$exists'=>1}},{'PDB'=>1,'_id'=>0});
while (my $d = $c->next) {
	next if $d->{'PDB'} =~ /[Nn]o/;
	my $id = $d->{'PDB'};
        $id =~ tr/a-z/A-Z/;
        $id =~ s/ *//g;
        print "-$id-\n";;
        $PDBCol->update({'_id'=>$id},{'$addToSet'=>{'MDDBS' => 'BNS'}});
}
