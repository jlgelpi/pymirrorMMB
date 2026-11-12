/* 
 * purgeGS.js cleans orphan fs.chunks
 */
function removeChunkIfNoOwner(chunk){
  //Look for the parent file
  var parentCount = db.fs.files.find({'_id' : chunk.files_id}).count();

  if (parentCount === 0 ){
     db.fs.chunks.remove({'_id': chunk._id});
     print("Removing chunk " + chunk._id);
  }
}
cursor=db.fs.chunks.find({},{'_id':1,files_id:1});
while (cursor.hasNext()) {
    removeChunkIfNoOwner(cursor.next());
}