ZIP := pdf-to-images-function.zip
SHELL := /bin/bash
FUNC_RUNTIME := python312
ENTRY := handler.handler
FUNC := pdf-to-images-function
S3_ENDPOINT_URL := https://storage.yandexcloud.net
AWS_REGION := ru-central1

export BFE_SA
export BFE_S3_BUCKET_NAME
export BFE_S3_ACCESS_KEY_ID
export BFE_S3_SECRET_ACCESS_KEY



git:
	@if [ -z "$(MSG)" ]; then echo 'ERROR: set MSG, e.g. make git MSG="feat: deploy function"'; exit 1; fi
	git add -A
	git commit -m "$(MSG)"
	git push origin main

build-zip:
	rm $(ZIP)
	zip -r $(ZIP) . -x 'patch.diff' '*/patch.diff' '.git/*' '*/.git/*' 'git/*' '*/git/*' 'tests/*' '*/tests/*' 'files/*' 'Makefile' '*/Makefile' 'README.md' '*/README.md' 'technical_specification.md' '*/technical_specification.md' '__pycache__/*' '*/__pycache__/*'



REQUIRED_ENV := BFE_S3_BUCKET_NAME BFE_S3_ACCESS_KEY_ID BFE_S3_SECRET_ACCESS_KEY BFE_S3_BUCKET_NAME BFE_S3_ACCESS_KEY_ID BFE_S3_SECRET_ACCESS_KEY

check-env:
	@for v in $(REQUIRED_ENV); do \
		val="$${!v}"; \
		if [ -z "$$val" ]; then echo "ERROR: $$v is empty"; exit 1; fi; \
		if printf "%s" "$$val" | LC_ALL=C grep -qP '[\x00-\x1F\x7F,]'; then \
			echo "ERROR: $$v contains newline/control/comma, sanitize it or use Lockbox"; exit 1; \
		fi; \
	done


ENV_ARGS = "S3_BUCKET_NAME=$(BFE_S3_BUCKET_NAME),S3_ENDPOINT_URL=$(S3_ENDPOINT_URL),AWS_ACCESS_KEY_ID=$(BFE_S3_ACCESS_KEY_ID),AWS_SECRET_ACCESS_KEY=$(BFE_S3_SECRET_ACCESS_KEY),AWS_REGION=$(AWS_REGION)"


deploy: check-env build-zip
	yc serverless function version create \
	  --function-name $(FUNC) \
	  --runtime $(FUNC_RUNTIME) \
	  --service-account-id $(BFE_SA) \
	  --entrypoint $(ENTRY) \
	  --source-path ./$(ZIP) \
	  --environment $(ENV_ARGS)