from django import forms

MAX_UPLOAD_MB = 20


class ImportForm(forms.Form):
    file = forms.FileField(label="Canvas export")
    course_code = forms.CharField(label="Code", max_length=50)
    course_name = forms.CharField(label="Name", max_length=250, required=False)

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith(".zip"):
            raise forms.ValidationError("Choose the .zip file that Canvas exported.")
        if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f"That file is over {MAX_UPLOAD_MB} MB.")
        return upload
