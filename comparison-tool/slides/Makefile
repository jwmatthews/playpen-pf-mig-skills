.PHONY: pdf html clean

pdf: slides.pdf
html: slides.html

slides.pdf: slides.md
	pandoc slides.md -t beamer -o slides.pdf \
		-V aspectratio=169 \
		-V fontsize=11pt \
		-V theme=Madrid

slides.html: slides.md style.css
	pandoc slides.md -t revealjs -s -o slides.html \
		-V revealjs-url=https://unpkg.com/reveal.js@5.1.0 \
		-V theme=white \
		-V transition=slide \
		-V slideNumber=true \
		-V width=1920 \
		-V height=1080 \
		--css=style.css

clean:
	rm -f slides.pdf slides.html
