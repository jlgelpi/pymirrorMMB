<?php
// Select character used for quoting text ["|']
$qChar='"';
$params = ['fmt'=> 'json', 'atoms'=>'block', 'noEmpty' => True];
$babelexe = "/usr/bin/babel";
$MDB_userName = "dataLoader";
$MDB_password = "mdbwany2015";
$MDB_hostname = "127.0.0.1";
$pdbConn = new MongoDB\Driver\Manager("mongodb://${MDB_userName}:${MDB_password}@${MDB_hostname}");
//$db = $pdbConn->FlexPortal;
//$monomersCol   = $db->PDB_Monomers;
$wconcern = new MongoDB\Driver\WriteConcern(MongoDB\Driver\WriteConcern::MAJORITY, 1000);

array_shift($argv);
foreach ($argv as $fn) {
    $monomers = file_get_contents($fn);
    if (preg_match("/gz$/", $fn)) {
        $monomers = gunzip($monomers);
    }
    foreach (preg_split("/data_(...)/", $monomers) as $mon) {
        if (!$mon) {
            continue;
        }
        $monData = parsemmCif($mon, $params);
        foreach (array_keys($monData['chem_comp']) as $k) {
            $monData[$k]= $monData['chem_comp'][$k];
        }
        $monData['_id']=$monData['id'];
        unset ($monData['id']);
        unset($monData['chem_comp']);
//        $ff= fopen("babel".uniqid().".pdb", 'w');
 //       fwrite($ff, prepPDB($monData['chem_comp_atom']['atom_records']));
//        fclose($ff);exit;
// Delete redundant comp_id fields
	print "-".$monData['_id']."-";
	foreach (array_keys($monData) as $k) {
		if (is_array($monData[$k]) and !is_assoc($monData[$k])) {
			$monData[$k] = array_map (function ($el) {unset($el['comp_id']);return $el;},$monData[$k]);
		}
	}
// Mongo insert
        $bulk = new MongoDB\Driver\BulkWrite();
        foreach (array_keys($monData) as $k) {
            $bulk->update(['_id' => $monData['_id']], ['$set' => [$k => $monData[$k]]]);
        }
        $pdbConn->executeBulkWrite('FlexPortal.PDB_Monomers', $bulk, $wconcern);
        print $monData['_id'] . "\n";
    }
}



/* mmCIF support
 * parsemmCif generate a PHP array structure, that can be shown as json or xml 
 */

function parsemmCif($cifData, $params) {
    set_time_limit(0);
    $groups = explode("#", $cifData);
    $data = [];
    while ($gr = array_shift($groups)) {
        $data = array_merge($data, _parsemmCifGroup($gr, $params));
    }
    return $data;
}

function _parsemmCifGroup($gr, $params) {
    $lines = explode("\n", $gr);
    array_shift($lines);
    if ($lines[0] == "loop_") {
        array_shift($lines);
        return _parsemmCifGroupLoop($lines, $params);
    } else {
        return _parsemmCifGroupNoLoop($lines, $params);
    }
}

function _parsemmCifGroupNoLoop($lines, $params) {
    $data = [];
    $nl = 0;
    $v = '';
    $k = '';
    while ($nl < count($lines)) {
        $l = _protectQuotedBlock($lines[$nl],$GLOBALS['qChar']);
        if (preg_match("/^_/", $l)) {
            $data = _addValue($data, $k, _unprotectQuotedBlock($v,$GLOBALS['qChar']), $params);
            list ($k, $v) = preg_split("/\s+/", $l);
        } else {
            $v .= preg_replace("/^;/", "", $l);
        }
        $nl++;
    }
    $data = _addValue($data, $k, _unprotectQuotedBlock($v,$GLOBALS['qChar']), $params);
    return $data;
}

function _parsemmCifGroupLoop($lines, $params) {
    $data = [];
    $fields = [];
    foreach ($lines as $l) {
        if (preg_match("/^_/", $l)) {
            list ($grup, $f) = explode(".", preg_replace("/^_/", "", $l));
            $fields[] = $f;
        }
    }
    if (!preg_match("/s$/", $grup) and ( $params['fmt'] == 'xml')) { // management lists in xml through plural/singular tags
        $grup .= "s";
        $grup = preg_replace("/ys$/", "ies", $grup); // proper plural when ..y :-)
    }
    if (preg_match("/atom_site/", $grup) or preg_match("/chem_comp_atom/",$grup)) {
        switch ($params['atoms']) {
            case "full":
                break;
            case "none":
            case "no":
                return [];
                break;
            case "block":
            default:
                $data[$grup]['fieldList'] = join(" ", $fields);
                $fields = ['atom_records'];
                $nl = 0;
                while ($nl < count($lines)) {
                    if (!preg_match("/^_/", $lines[$nl])) {
                        $data[$grup]['atom_records'][] = $lines[$nl];
                    }
                    $nl++;
                }
                return $data;
        }
    }
    $nl = 0;
    $dataFields = [];
    while ($nl < count($lines)) {
//remove trailing spaces
	$lines[$nl] = preg_replace("/ *$/","", $lines[$nl]);
        if ($lines[$nl] and !preg_match("/^_/", $lines[$nl])) {
            if (preg_match("/^;/", $lines[$nl])) { // read block between ";" and add as a quoted single line 
                $concatBl = $lines[$nl];
                $nl++;
                while ($nl < count($lines) and ! preg_match("/^;/", $lines[$nl])) {
                    $concatBl .= $lines[$nl];
                    $nl++;
                }
                $concatBl .= $lines[$nl];
                $lines[$nl] = str_replace(";", $GLOBALS['qChar'], $concatBl);
                $concatBl = '';
            }
            $l = _protectQuotedBlock($lines[$nl],$GLOBALS['qChar']);
            $newData = preg_split("/\s+/", $l);
            $dataFields = array_merge($dataFields, $newData);
        }
        $nl++;
    }
    // Distribute $dataFields among n records of m fields each, skip empties
    $nf = 0;
    while ($nf < count($dataFields)) {
        $dataList = [];
        for ($i = 0; $i < count($fields); $i++) {
            if ($dataFields[$nf] === '') {
                $nf++;
            }
            $dataList = _addValue($dataList, $fields[$i], _unprotectQuotedBlock($dataFields[$nf],$GLOBALS['qChar']), $params);
            $nf++;
        }
        if ($dataList) {
            $data[$grup][] = $dataList;
        }
    }
    return $data;
}

function _addValue($data, $k, $v, $params) {
    $k = preg_replace("/^_/", "", preg_replace("/\s+$/", "", $k));
    if (isset($params['noEmpty'])) {
        $v = preg_replace("/^\?$/", "", $v);
    }
    if ($k and ( $v !== '')) {
        if (!preg_match('/\./', $k)) {
            if (($params['fmt'] == "xml")) {
                $k = preg_replace("/s$/", "s_", $k); // avoid open lists in xml due to final "s"
            }
            $data[$k] = $v;
        } else {
            $kk = explode(".", $k);
            if (($params['fmt'] == "xml")) {
                $kk[0] = preg_replace("/s$/", "s_", $kk[0]);
                $kk[1] = preg_replace("/s$/", "s_", $kk[1]);
            }
            $data[$kk[0]][$kk[1]] = $v;
        }
    }
    return $data;
}

function _protectQuotedBlock($l,$q) { // process 'ccc, cc' en 1 block
    return preg_replace_callback(
       	    "/$q([^$q]*)$q/", function ($a) {
        return preg_replace("/\s/", '#', $a[0]);
    }
       	    , $l);

}

function _unprotectQuotedBlock($l,$q) {
    return str_replace("#", " ", str_replace($q, "",$l));
}

function is_assoc($var)
{
        return is_array($var) && array_diff_key($var,array_keys(array_keys($var)));
}
//_chem_comp_atom.comp_id 
//_chem_comp_atom.atom_id 
//_chem_comp_atom.alt_atom_id 
//_chem_comp_atom.type_symbol 
//_chem_comp_atom.charge 
//_chem_comp_atom.pdbx_align 
//_chem_comp_atom.pdbx_aromatic_flag 
//_chem_comp_atom.pdbx_leaving_atom_flag 
//_chem_comp_atom.pdbx_stereo_config 
//_chem_comp_atom.model_Cartn_x 
//_chem_comp_atom.model_Cartn_y 
//_chem_comp_atom.model_Cartn_z 
//_chem_comp_atom.pdbx_model_Cartn_x_ideal 
//_chem_comp_atom.pdbx_model_Cartn_y_ideal 
//_chem_comp_atom.pdbx_model_Cartn_z_ideal 
//_chem_comp_atom.pdbx_component_atom_id 
//_chem_comp_atom.pdbx_component_comp_id 
//_chem_comp_atom.pdbx_ordinal 

//HETATM  266  CB  TYR A  87      47.871  88.009  42.875  1.00 16.10           C 
//HETATM ffffssss ssss A   1    ffffffffffffffffffffffff                       s

function prepPDB ($cifLines) { // preps a simple PDB with coordinates data
    $pdb='';
    foreach ($cifLines as $l) {
        $data = preg_split("/\s+/",$l);
        if ($data[0]) {
            $pdb.= sprintf ("HETATM %4.0f  %-3s%4s A   1    %8.3f%8.3f%8.3f                       %s\n",$data[17],$data[1],$data[0],$data[9],$data[10],$data[11],$data[3]);
        }
    }
    return $pdb;
}
