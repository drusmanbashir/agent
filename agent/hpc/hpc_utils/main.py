
# %%

# upload project folder
# %%
import os

from fran.managers.project import Project

from fran.utils.fileio import load_dict, load_yaml, save_dict
common_vars_filename = os.environ["FRAN_COMMON_PATHS"]
common_vars = load_yaml(common_vars_filename)


# %%
def fix_bboxes_filenames(bboxes_info,dest_hpc_folder):
    bboxes_out=[]
    for bb in bboxes_info:
        src_fname = bb['filename']
        src_folder =src_fname.parent.parent.parent
        dest_fname = src_fname.str_replace(str(src_folder),str(dest_hpc_folder))
        bb['filename']=dest_fname
        bboxes_out.append(bb)
    return bboxes_out

# %%
def main(args):
    P = Project(project_title=args.t)
    fd=P.fixed_spacings_folder
    fs = fd.glob("*")
    subfolders =[f for f in fs if f.is_dir()==True]
    for subfolder in subfolders:
        bboxesinfo_fn = subfolder/("bboxes_info")
        print("Altering bboxesfn: {}".format(bboxesinfo_fn))
        bboxesinfo = load_dict(bboxesinfo_fn)
        print("Sample source fn: {}".format(bboxesinfo[0]['filename']))
        bbout = fix_bboxes_filenames(bboxesinfo,fd)
        print("Sample fixed fn: {}\n".format(bbout[0]['filename']))
        save_dict(bbout,bboxesinfo_fn)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fix paths")
    parser.add_argument("-t", help="project title")#, required=True)
    args = parser.parse_known_args()[0]
    main(args)



