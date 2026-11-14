i cloned some repos, and did some changes to them, and wanna create,commit,push to my own account
task :
for every subdir in current dir, remove connected remote and everything related thatneeds to be cleaned, 
then create a git repo using:
gh repo create --public --source=. <repo-name=name of dirwe are in it>

if already exists, try commit, push
else  commit last changes (if any) , push

dont remove any dir or subdirs

all repo i cloned are in current folder (subdirs of .)
automate this with a bash script
gh auth is ok, no need to check