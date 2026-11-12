mol load pdb ##fpdb##
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
render TachyonInternal ##ftmp##
quit
