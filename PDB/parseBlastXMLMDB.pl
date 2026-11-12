#!/usr/bin/perl
use MongoDB;
use MongoDB::OID;
use XML::LibXML;
use strict;
use Data::Dumper;
#
my $DB = shift;
my $tag0;
if ($DB eq "swp") {
	$tag0= "swpHit";
} elsif ($DB eq "uniref") {
	$tag0= "unirefHit";
} else {
	die "ERROR"
}
	
#XML tags
my $inibloc = "Iteration";
my $endbloc = "/Iteration";
my $querydef = "Iteration_query-def";
my $querylen = "Iteration_query-len";
my $hittag = "Hit";
my $hitdef = "Hit_def";
my $hitfields = ['Hit_len','Hsp_evalue','Hsp_query-from','Hsp_query-to','Hsp_hit-from','Hsp_hit-to','Hsp_identity','Hsp_align-len'];
my $hittxtfields = ['Hit_def','Hit_id'];
#
my $parser = XML::LibXML->new;
my $chunk="";
my $mconn = MongoDB::MongoClient->new(host => '127.0.0.1');
$mconn->authenticate ('admin','dataLoader','mdbwany2015');
my $db = $mconn->get_database( 'FlexPortal' );
#
my $chainCol = $db->get_collection('chain');
#
#my $stProts = $dbh->prepare ("INSERT INTO Proteines (idProt,descripcio,length,source) VALUES (?,?,?,?)");
#my $stHits = $dbh->prepare ("INSERT INTO Hits (idQuery,idHit,evalue,query_from,query_to,hit_from,hit_to,identity,align_len) VALUES (?,?,?,?,?,?,?,?,?)");
my %Prots;
#
my $NP = 1;
if ($ARGV[0] eq "-np") {
	my $dum = shift;
	$NP = shift;
}

while (<>) {
	if (/<$endbloc>/) {
		$chunk .= $_;
		my $data = procesa ($chunk);
		my ($pdb,$ch) = split ' ',substr($data->{'query'},0,7);
		$pdb =~ tr/a-z/A-Z/;
		$ch =~s/ //g;
		my $idQ = $pdb."_".$ch;
		my $hit = $data->{'hits'}->[0];
		my $idH;
if ($DB eq "swp") {
		my @hitDef = split /\|/, $hit->{$hitdef};
		$idH = $hitDef[1];
} elsif ($DB eq "uniref") {
		my @hitDef = split ' ', $hit->{$hitdef};
		$idH = $hitDef[0];
		$idH =~ s/UniRef100_//;
} else {die "ERROR"}
		#print "$idQ : $idH\n";
              #print Dumper($hit)."\n";
     	$chainCol->update(
		     {'_id' => $idQ},
	     {'$set' => 
		          {$tag0 => {
    		          'idHit' => $idH,
	     	          'hit' => $hit
	           	     }
	           	     }
   		     }
	);
	}
	if (/<$inibloc>/) {
		$chunk = $_;
	}elsif ($chunk) {
		$chunk .= $_;
	}
}
print "Parsing Blast XML done\n";

sub procesa {
	my $chunk= shift;
	my $xml = $parser->parse_string($chunk);
	my $doc = $xml->getDocumentElement();
	my $query_def = $doc->getElementsByTagName($querydef)->string_value();
	my $query_len = $doc->getElementsByTagName($querylen)->string_value();
	my @hits = $doc->getElementsByTagName($hittag);
	my $data = {'query' => $query_def, 'length' => $query_len, 'hits' => ()};
	foreach my $hit (@hits) {
		my $hitData = {};
		foreach my $k (@$hittxtfields) {
			$hitData->{$k} = $hit->getElementsByTagName($k)->string_value();
		}
		foreach my $k (@$hitfields) {
			$hitData->{$k} = $hit->getElementsByTagName($k)->string_value()+0;
		}
		push @{$data->{'hits'}},$hitData;
	}
	return $data;
}



sub trim {
	my $a = shift;
	$a =~ s/^ *//;
	$a =~ s/ *$//;
	return $a
}

sub procDef {
	my $data = shift;
	print "#$data#\n";
	my @f = split /\|/,$data;
	my $id = trim (join '|',@f[0 .. 3]);
	my $desc = trim ($f[4]);
	$desc =~ s/\[([^\]]*)\]//;
	my $source = trim ($1);
	$desc = trim ($desc);
	return ($id, $desc, $source);
}
