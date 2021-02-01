#!/usr/bin/env python3
#     Y__   structo   
#   _/u u\_    (c) nemo
#    \_^_/     
# .==|>o<|==:=L
# '=c|___|     
#    /  |      
#   _\  |_      


import sys
import tempfile
import secrets
from clang.cindex import *
from pprint import pprint

class structo:
    def __init__(self):
        Config.set_library_file("/Library/Developer/CommandLineTools/usr/lib/libclang.dylib") # mac port
        self.__index = Index.create()
        
        self.__structs = [] # list of parsed structs to operate on
        self.__offsets = [] # our built offsets for the structs

    def __find_struct(self,node):
    #
    # returns the first struct type in the header
    #
            for c in node.get_children():
                if(c.kind.name == "STRUCT_DECL"):
                    return c
                else:
                    return self.__find_struct(c)
        
    def __parse_from_mem(self,ccode):
    # 
    # use a temp file to parse c code from a string
    #
        fp = tempfile.NamedTemporaryFile(delete=True, suffix=".h")
        fp.write(ccode.encode())
        fp.flush()
        parse = self.__index.parse(fp.name)
        fp.close()      # deletes the file
        return parse

    def __struct_to_offsets(self,node):
    #
    # generate offsets data structure from parsed AST
    # 
        offsets = []   
        curroffset = 0
        for c in node.get_children():
            #sizestr = c.type.get_canonical().spelling
            #print(c.type.get_size())
            #print(sizestr)
            offsets.append({"name": c.spelling, "size": c.type.get_size(), "offset": curroffset, "type": c.type.get_canonical().spelling })
            curroffset += c.type.get_size()
        return offsets

    def __create_offsets(self):
    #
    # create an offsets data structure for each struct
    #
        i = 0 
        for s in self.__structs:
            node = s.cursor 
            structnode = self.__find_struct(node)
            self.__offsets.append(self.__struct_to_offsets(structnode))
            i+=1

    def dump_structs(self):
    # 
    # debug function for listing struct info
    # 
        i = 0
        for off in self.__offsets:
            print("[*] Offsets for struct #%u" % i)
            pprint(off)
            i+=1

    def __offsets_to_c(self,name,offsets):
    #
    # take our offsets dictonary and walk it, assembling a C structure baed on 
    # the contents
    #
        cstruct = "struct %s {\n" % name
        # name size offset type
        for off in offsets:
            arrsz = ""
            tp = off["type"]
            arr = tp.find("[") 
            if(arr != -1):
                tp = off["type"][0:arr-1]
                arrsz = off["type"][arr:]
            cstruct += ("\t%s %s%s;\n" % (tp,off["name"],arrsz))
        cstruct += "};"
        return cstruct


    def insert_element(self,cstruct,offset,ccode):
    # 
    # insert element into a pad within our offsets blob, restructure pad into 2 pads if necessary 
    #
        tu = self.__parse_from_mem(cstruct)
        node = tu.cursor
        structnode = self.__find_struct(node)
        offsets = self.__struct_to_offsets(structnode)

        print("parsed struct:")
        pprint(offsets)

        newoffsets = []
        tu = self.__parse_from_mem(ccode)
        node = tu.cursor
        
        c = next(node.get_children())
        element_name = c.spelling               # insert with same name..
        element_size = c.type.get_size()        # size to insert
        
        for i in range(0,len(offsets)):
            off = offsets[i]['offset']
            sz = offsets[i]['size']
            if(off <= offset):  # offset is lower or equal to where we need to insert
                if(off + sz > offset):
                    if(offsets[i]['name'][0:3] == "pad"): # element is a pad we need to split.
                        subsize = 0
                        if(off != offset):
                            newpadsz = offset - off # initial pad
                            newname = "pad_" + secrets.token_hex(2)
                            newoffsets.append({"name": newname, "size": newpadsz, "offset": off, "type": "unsigned char [%u]" % newpadsz})
                            subsize += newpadsz
                            off += newpadsz # move forward
                        # insert the element passed in
                        newoffsets.append({"name": element_name, "size": element_size, "offset": off, "type": c.type.get_canonical().spelling})
                        subsize += element_size
                        off += element_size
                        if(sz - subsize > 0):
                            newoffsets.append({"name": "pad_" + secrets.token_hex(2), "size": sz-subsize, "offset": off, "type": "unsigned char [%u]" % (sz-subsize)})
                        elif(sz -subsize < 0):
                            raise ValueError("Pad not large enough to house new type.. Fail")
                        continue
            newoffsets.append(offsets[i]) 
            print("newoffsets:")
            pprint(newoffsets)
        return self.__offsets_to_c(structnode.spelling,newoffsets)

    def __validate_offsets(self,offsets):
    # 
    # run through offsets to make sure no elements overlap
    #
        for off in offsets:
            for off2 in offsets:
                if(off["name"] == off2["name"]): # same element
                    continue
                if(off["offset"] + off["size"] <= off2["offset"]): # offset + size smaller than offset
                    continue
                if(off["offset"] >= off2["offset"] + off2["size"]):
                    continue
                print("---[MISMATCH]---")
                print(off)
                print(off2)
                print("----------------")
                return False
        return True

    def __insert_pads(self,offsets,tsz):
    #
    # insert pads in between gaps in members.
    #
        newoffsets = []
        lastoff = 0
        for i in range(0,len(offsets)):
            if(offsets[i]["offset"] != lastoff):
                # we need to pad
                newname = "pad_" + secrets.token_hex(2)
                sz = offsets[i]["offset"] - lastoff
                newoffsets.append({"name": newname, "size": sz, "offset": lastoff, "type": "unsigned char [%u]" % sz})
            newoffsets.append(offsets[i])
            lastoff = offsets[i]["offset"]
        end = newoffsets[-1]["offset"] + newoffsets[-1]["size"]
        if(tsz > end):
            newname = "pad_" + secrets.token_hex(2)
            newoffsets.append({"name": newname, "size": tsz - end, "offset": end, "type": "unsigned char [%u]" % (tsz-end)})
        return newoffsets
	
    def merge_structs(self,hdr1fn,hdr2fn):
    #
    # Merge the two structs in our example and returna c representation of the new struct
    #
        nopads = [] # temporary array to store non pad elements
        newoffsets = [] # create our new offsets array to represent the merge of two structs

        self.__structs.append(self.__index.parse(hdr1fn))
        self.__structs.append(self.__index.parse(hdr2fn))
        self.__create_offsets()
    
        node = self.__structs[0].cursor
        structnode = self.__find_struct(node)  # use this to get the name for our new struct
        tsz1 = self.__offsets[0][-1]["offset"] + self.__offsets[0][-1]["size"] 
        tsz2 = self.__offsets[1][-1]["offset"] + self.__offsets[1][-1]["size"] 
        tsz = max(tsz1,tsz2)

        for off in self.__offsets[0]:
            if((len(off["name"]) < 3) or off["name"][0:3] != "pad"):
                nopads.append(off)
        for off in self.__offsets[1]:
            if((len(off["name"]) < 3) or off["name"][0:3] != "pad"):
                nopads.append(off)
        if(not self.__validate_offsets(nopads)):
            raise(ValueError("Overlap detected in struct elements"))
            
        snopads = sorted(nopads, key = lambda i: i['offset'])
        for i in range(1,len(snopads)-1):
            if(snopads[i]["name"] == snopads[i-1]["name"] and snopads[i]["size"] == snopads[i-1]["size"]):
                snopads.remove(snopads[i]) # remove duplicates
        newoffsets = self.__insert_pads(snopads,tsz)
        
        return self.__offsets_to_c(structnode.spelling,newoffsets)
            
def usage(argv):
    print("usage: %s <header1> <header2>" % argv[0])
    sys.exit(1)

def main(argv):
    if(len(argv) != 3):
        usage(argv)
    
    hdr1fn = argv[1]
    hdr2fn = argv[2]

    print("[+] Parsing our header files (%s) (%s)" % (hdr1fn,hdr2fn))
    s = structo()
    
    print("[+] Merging structs")
    result = s.merge_structs(hdr1fn,hdr2fn)
    
    print("[+] Merged struct:")
    print(result)

    print("[+] Inserting element into struct.")
    print(s.insert_element(result,56,"int bob;")) # test XXX

if __name__ == "__main__":
    main(sys.argv)
