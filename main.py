from datetime import date
from flask import Flask, abort, render_template, redirect, url_for, flash, session, request
from flask_bootstrap import Bootstrap5
from flask_ckeditor import CKEditor
from flask_gravatar import Gravatar
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship, DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String, Text, ForeignKey
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from forms import RegisterForm, CreatePostForm, LoginForm, CommentForm
from datetime import datetime
from smtplib import SMTP_SSL as SMTP
import os


MY_EMAIL = os.environ.get('MY_EMAIL')
PASSWORD = os.environ.get('PASSWORD')

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_KEY')
ckeditor = CKEditor(app)
Bootstrap5(app)
gravatar = Gravatar(
    app,
    size=100,
    rating='g',
    default='retro',
    force_default=False,
    force_lower=False,
    use_ssl=False,
    base_url=None
)


login_manager = LoginManager()
login_manager.init_app(app)


#Create a user_loader callback
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

# CREATE DATABASE
class Base(DeclarativeBase):
    pass
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DB_URI')
db = SQLAlchemy(model_class=Base)
db.init_app(app)


# CONFIGURE TABLES
class BlogPost(db.Model):
    __tablename__ = "blog_posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(250), unique=True, nullable=False)
    subtitle: Mapped[str] = mapped_column(String(250), nullable=False)
    date: Mapped[str] = mapped_column(String(250), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    img_url: Mapped[str] = mapped_column(String(250), nullable=False)
    author = relationship('User', back_populates='posts')
    author_id: Mapped[int] = mapped_column(Integer, db.ForeignKey('users.id'), nullable=False)
    # Define one-to-many relationship with Comment
    comments = relationship("Comment", back_populates='parent_post')



class User(UserMixin, db.Model):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(100), unique=True)
    password: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(1000))
    #Define one-to-many relationship with BlogPost
    posts = relationship("BlogPost", back_populates='author')
    # Define one-to-many relationship with Comment
    comments = relationship("Comment", back_populates='comment_author')

#Comment Table in DB
class Comment(db.Model):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # child relationship to User Table
    author_id: Mapped[int] = mapped_column(Integer, db.ForeignKey('users.id'), nullable=False)
    comment_author = relationship('User', back_populates='comments')

    #child relationship to Blogpost Table
    parent_post = relationship('BlogPost', back_populates='comments')
    post_id: Mapped[int] = mapped_column(Integer, db.ForeignKey('blog_posts.id'), nullable=False)

with app.app_context():
    db.create_all()


def admin_only(route_func):
    @wraps(route_func)
    def wrapper_func(*args, **kwargs):
        if current_user.is_authenticated and current_user.id == 1:
            return route_func(*args, **kwargs)
        else:
            return abort(403)
    return wrapper_func


@app.route('/register', methods=["GET","POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        user_email = form.Email.data
        user_password = form.Password.data
        encrypted_password = generate_password_hash(user_password, method='pbkdf2:sha256', salt_length=8)
        user = db.session.execute(db.select(User).where(User.email == user_email)).scalar()
        if not user:
            new_user = User(
                name=form.Name.data,
                email=form.Email.data,
                password=encrypted_password
            )
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            return redirect(url_for('get_all_posts', id=current_user.id))
        if user:
            flash("You've already signed up with that email. log in instead")
            return redirect(url_for("login"))
    return render_template("register.html", form=form, logged_in=current_user.is_authenticated)


@app.route('/login', methods=["GET","POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user_pass = form.Password.data
        user_email = form.Email.data
        user = db.session.execute(db.select(User).where(User.email == user_email)).scalar()
        if user:
            if check_password_hash(user.password, user_pass):
                login_user(user)
                return redirect(url_for('get_all_posts'))
            else:
                flash("Password incorrect, please try again.")
                return redirect(url_for('login'))
        else:
            flash("Email does not exist in our system, please try again.")
            return redirect(url_for('login'))
    return render_template("login.html", form=form, logged_in=current_user.is_authenticated)


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('get_all_posts'))


@app.route('/')
def get_all_posts():
    result = db.session.execute(db.select(BlogPost))
    posts = result.scalars().all()
    return render_template("index.html", all_posts=posts, logged_in=current_user.is_authenticated)



@app.route("/post/<int:post_id>", methods=["GET", "POST"])
def show_post(post_id):
    form = CommentForm()
    requested_post = db.get_or_404(BlogPost, post_id)
    if form.validate_on_submit():
        if current_user.is_authenticated:
            new_comment = Comment(
                text=form.comment.data,
                comment_author=current_user,
                parent_post=requested_post

            )
            db.session.add(new_comment)
            db.session.commit()
            return redirect(url_for('show_post', post_id=post_id))
        else:
            flash("You need to be logged in or registered to comment")
            return redirect(url_for('login'))
    return render_template("post.html", post=requested_post, logged_in=current_user.is_authenticated,
                           form=form, gravatar=gravatar)

#Delete a comment
@app.route("/delete-comment/<int:comment_id>")
def delete_comment(comment_id):
    comment_to_delete = db.get_or_404(Comment, comment_id)
    post_id = comment_to_delete.post_id
    if current_user.is_authenticated:
        db.session.delete(comment_to_delete)
        db.session.commit()
    return redirect(url_for('show_post', post_id=post_id))


@app.route("/new-post", methods=["GET", "POST"])
@admin_only
def add_new_post():
    form = CreatePostForm()
    if form.validate_on_submit():
        new_post = BlogPost(
            title=form.title.data,
            subtitle=form.subtitle.data,
            body=form.body.data,
            img_url=form.img_url.data,
            author=current_user,
            date=date.today().strftime("%B %d, %Y")
        )
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for("get_all_posts"))
    return render_template("make-post.html", form=form)


@app.route("/edit-post/<int:post_id>", methods=["GET", "POST"])
@admin_only
def edit_post(post_id):
    post = db.get_or_404(BlogPost, post_id)
    edit_form = CreatePostForm(
        title=post.title,
        subtitle=post.subtitle,
        img_url=post.img_url,
        author=post.author,
        body=post.body
    )
    if edit_form.validate_on_submit():
        post.title = edit_form.title.data
        post.subtitle = edit_form.subtitle.data
        post.img_url = edit_form.img_url.data
        post.author = current_user
        post.body = edit_form.body.data
        db.session.commit()
        return redirect(url_for("show_post", post_id=post.id))
    return render_template("make-post.html", form=edit_form, is_edit=True)



@app.route("/delete/<int:post_id>")
@admin_only
def delete_post(post_id):
    post_to_delete = db.get_or_404(BlogPost, post_id)
    db.session.delete(post_to_delete)
    db.session.commit()
    return redirect(url_for('get_all_posts'))



@app.route('/about')
def about():
    current_date = datetime.now()
    return render_template("about.html", year=current_date, logged_in=current_user.is_authenticated)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    current_date = datetime.now()
    if request.method == 'GET':
        return render_template("contact.html", year=current_date, msg_sent=False, logged_in=current_user.is_authenticated)
    elif request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        message = request.form['message']
        with SMTP("smtp.gmail.com", 465) as connection:
            connection.login(MY_EMAIL, PASSWORD)
            connection.sendmail(
                from_addr=MY_EMAIL,
                to_addrs=MY_EMAIL,
                msg=f"Subject: New Message from blog \n\nName: {name}\nUser email: {email}\nPhone Number: {phone}\nMessage: {message}"
            )
        return render_template("contact.html", year=current_date, msg_sent=True, logged_in=current_user.is_authenticated)


if __name__ == "__main__":
    app.run(debug=False)
